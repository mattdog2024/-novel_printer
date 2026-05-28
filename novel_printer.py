import os
import re
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

import chardet
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


APP_TITLE = "小说 A4 自动排版打印工具"


@dataclass(frozen=True)
class LayoutMode:
    name: str
    font_size: float
    line_spacing: float
    margin_mm: float
    column_gap_mm: float
    first_line_indent_chars: int
    description: str


MODES = {
    "黄金设置": LayoutMode(
        name="黄金设置",
        font_size=9.5,
        line_spacing=1.0,
        margin_mm=10,
        column_gap_mm=8,
        first_line_indent_chars=2,
        description="A4 横向、两栏、窄边距、宋体、单倍行距，适合大多数小说。",
    ),
    "省纸模式": LayoutMode(
        name="省纸模式",
        font_size=8.8,
        line_spacing=0.95,
        margin_mm=8,
        column_gap_mm=6,
        first_line_indent_chars=2,
        description="字更小、边距更窄，适合很长的小说。",
    ),
    "舒适阅读": LayoutMode(
        name="舒适阅读",
        font_size=10.5,
        line_spacing=1.18,
        margin_mm=13,
        column_gap_mm=9,
        first_line_indent_chars=2,
        description="字更大、行距更舒服，适合慢慢看。",
    ),
}


CHAPTER_PATTERN = re.compile(
    r"^\s*((第\s*[0-9零一二三四五六七八九十百千万两〇○]+\s*[章节回卷部篇集])|"
    r"([上中下]卷)|"
    r"(卷\s*[0-9零一二三四五六七八九十百千万两〇○]+)|"
    r"(chapter\s+\d+))",
    re.IGNORECASE,
)


def mm(value: float) -> float:
    return value * 72 / 25.4


def register_fonts() -> tuple[str, str]:
    regular_name = "NovelSong"
    bold_name = "NovelSongBold"
    candidates = [
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simfang.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
    ]

    for font_path in candidates:
        if not os.path.exists(font_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(regular_name, font_path))
            pdfmetrics.registerFont(TTFont(bold_name, font_path))
            return regular_name, bold_name
        except Exception:
            continue

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light", "STSong-Light"


FONT_NAME, FONT_BOLD_NAME = register_fonts()


def read_txt(path: str) -> str:
    with open(path, "rb") as file:
        raw = file.read()

    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="ignore")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="ignore")

    guess = chardet.detect(raw)
    encoding = guess.get("encoding") or "utf-8"
    for candidate in [encoding, "utf-8", "gb18030", "gbk", "big5"]:
        try:
            return raw.decode(candidate, errors="ignore")
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")


def clean_text(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ")
    lines = []

    ad_patterns = [
        "本书来自",
        "手机用户请浏览",
        "最新网址",
        "请收藏本站",
        "无弹窗",
        "txt下载",
        "www.",
        "http://",
        "https://",
    ]

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        line = re.sub(r"[ \t]+", " ", line)
        if not line:
            continue
        lower_line = line.lower()
        if any(pattern in lower_line for pattern in ad_patterns):
            continue
        lines.append(line)

    return lines


def is_chapter_title(line: str) -> bool:
    return len(line) <= 40 and bool(CHAPTER_PATTERN.match(line))


def wrap_text(text: str, max_width: float, font_name: str, font_size: float) -> list[str]:
    result = []
    current = ""

    for char in text:
        candidate = current + char
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue
        if current:
            result.append(current)
        current = char

    if current:
        result.append(current)
    return result or [""]


class PdfWriter:
    def __init__(self, output_path: str, mode: LayoutMode):
        self.output_path = output_path
        self.mode = mode
        self.page_width, self.page_height = landscape(A4)
        self.margin = mm(mode.margin_mm)
        self.column_gap = mm(mode.column_gap_mm)
        self.column_width = (self.page_width - self.margin * 2 - self.column_gap) / 2
        self.top = self.page_height - self.margin
        self.bottom = self.margin + mm(6)
        self.line_height = mode.font_size * mode.line_spacing + 1.2
        self.page_number = 0
        self.column = 0
        self.y = self.top
        self.canvas = canvas.Canvas(output_path, pagesize=(self.page_width, self.page_height))
        self.new_page()

    def new_page(self):
        if self.page_number:
            self.draw_footer()
            self.canvas.showPage()
        self.page_number += 1
        self.column = 0
        self.y = self.top
        self.canvas.setTitle(os.path.basename(self.output_path))

    def draw_footer(self):
        self.canvas.setFont(FONT_NAME, 7)
        self.canvas.drawCentredString(self.page_width / 2, mm(5), str(self.page_number))

    def next_column_or_page(self):
        if self.column == 0:
            self.column = 1
            self.y = self.top
        else:
            self.new_page()

    def x_for_column(self) -> float:
        return self.margin + self.column * (self.column_width + self.column_gap)

    def ensure_space(self, needed: float):
        if self.y - needed < self.bottom:
            self.next_column_or_page()

    def draw_heading(self, text: str):
        heading_size = self.mode.font_size + 1.2
        lines = wrap_text(text, self.column_width, FONT_BOLD_NAME, heading_size)
        needed = len(lines) * (heading_size + 2) + self.line_height * 0.8
        self.ensure_space(needed)
        self.y -= self.line_height * 0.4
        self.canvas.setFont(FONT_BOLD_NAME, heading_size)
        for line in lines:
            self.canvas.drawCentredString(self.x_for_column() + self.column_width / 2, self.y, line)
            self.y -= heading_size + 2
        self.y -= self.line_height * 0.3

    def draw_paragraph(self, text: str):
        indent_width = pdfmetrics.stringWidth("中" * self.mode.first_line_indent_chars, FONT_NAME, self.mode.font_size)
        first_width = self.column_width - indent_width
        first_lines = wrap_text(text, first_width, FONT_NAME, self.mode.font_size)

        if len(first_lines) <= 1:
            lines = [(first_lines[0], indent_width)]
        else:
            rest_text = text[len(first_lines[0]) :]
            rest_lines = wrap_text(rest_text, self.column_width, FONT_NAME, self.mode.font_size)
            lines = [(first_lines[0], indent_width)] + [(line, 0) for line in rest_lines]

        self.canvas.setFont(FONT_NAME, self.mode.font_size)
        for line, indent in lines:
            self.ensure_space(self.line_height)
            self.canvas.drawString(self.x_for_column() + indent, self.y, line)
            self.y -= self.line_height

    def save(self):
        self.draw_footer()
        self.canvas.save()


def build_pdf(txt_path: str, output_path: str, mode_name: str) -> tuple[int, int]:
    mode = MODES[mode_name]
    lines = clean_text(read_txt(txt_path))
    if not lines:
        raise ValueError("这个 TXT 里没有读到正文。")

    writer = PdfWriter(output_path, mode)
    for line in lines:
        if is_chapter_title(line):
            writer.draw_heading(line)
        else:
            writer.draw_paragraph(line)
    writer.save()
    return len(lines), writer.page_number


def open_file(path: str):
    os.startfile(path)


def print_file(path: str):
    os.startfile(path, "print")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("720x420")
        self.minsize(680, 390)
        self.txt_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.mode_name = tk.StringVar(value="黄金设置")
        self.status = tk.StringVar(value="请选择一个 TXT 小说文件。")
        self.create_widgets()

    def create_widgets(self):
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)

        title = ttk.Label(root, text=APP_TITLE, font=("Microsoft YaHei UI", 18, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(root, text="默认使用 A4 横向、两栏、窄边距、宋体、单倍行距。生成 PDF 后就可以打印。")
        subtitle.pack(anchor="w", pady=(4, 16))

        file_row = ttk.Frame(root)
        file_row.pack(fill="x", pady=6)
        ttk.Label(file_row, text="小说文件", width=10).pack(side="left")
        ttk.Entry(file_row, textvariable=self.txt_path).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(file_row, text="选择 TXT", command=self.choose_txt).pack(side="left")

        mode_frame = ttk.LabelFrame(root, text="排版模式", padding=12)
        mode_frame.pack(fill="x", pady=12)
        for name in MODES:
            ttk.Radiobutton(
                mode_frame,
                text=f"{name}：{MODES[name].description}",
                variable=self.mode_name,
                value=name,
            ).pack(anchor="w", pady=3)

        output_row = ttk.Frame(root)
        output_row.pack(fill="x", pady=6)
        ttk.Label(output_row, text="输出 PDF", width=10).pack(side="left")
        ttk.Entry(output_row, textvariable=self.output_path).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(output_row, text="保存到", command=self.choose_output).pack(side="left")

        button_row = ttk.Frame(root)
        button_row.pack(fill="x", pady=(16, 8))
        ttk.Button(button_row, text="生成 PDF", command=self.generate).pack(side="left")
        ttk.Button(button_row, text="打开 PDF", command=self.open_pdf).pack(side="left", padx=8)
        ttk.Button(button_row, text="直接打印", command=self.print_pdf).pack(side="left")

        status = ttk.Label(root, textvariable=self.status, foreground="#245a8d", wraplength=640)
        status.pack(anchor="w", pady=(12, 0))

    def choose_txt(self):
        path = filedialog.askopenfilename(
            title="选择 TXT 小说",
            filetypes=[("TXT 小说", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.txt_path.set(path)
        base = os.path.splitext(path)[0] + "_A4排版.pdf"
        self.output_path.set(base)
        self.status.set("已选择 TXT。点“生成 PDF”就可以排版。")

    def choose_output(self):
        initial = self.output_path.get() or "小说_A4排版.pdf"
        path = filedialog.asksaveasfilename(
            title="保存 PDF",
            defaultextension=".pdf",
            initialfile=os.path.basename(initial),
            filetypes=[("PDF 文件", "*.pdf")],
        )
        if path:
            self.output_path.set(path)

    def generate(self):
        txt_path = self.txt_path.get().strip()
        output_path = self.output_path.get().strip()
        if not txt_path or not os.path.exists(txt_path):
            messagebox.showwarning(APP_TITLE, "请先选择 TXT 小说文件。")
            return
        if not output_path:
            output_path = os.path.splitext(txt_path)[0] + "_A4排版.pdf"
            self.output_path.set(output_path)

        try:
            self.status.set("正在排版，请稍等。")
            self.update_idletasks()
            line_count, page_count = build_pdf(txt_path, output_path, self.mode_name.get())
            self.status.set(f"生成完成：共处理 {line_count} 行正文，PDF 共 {page_count} 页。双面打印时在打印窗口选择“双面”。")
            messagebox.showinfo(APP_TITLE, f"PDF 已生成。\n\n页数：{page_count}\n位置：{output_path}")
        except Exception as exc:
            self.status.set("生成失败，请换一个 TXT 或重新选择保存位置。")
            messagebox.showerror(APP_TITLE, f"生成失败：{exc}")

    def open_pdf(self):
        path = self.output_path.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning(APP_TITLE, "请先生成 PDF。")
            return
        open_file(path)

    def print_pdf(self):
        path = self.output_path.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning(APP_TITLE, "请先生成 PDF。")
            return
        try:
            print_file(path)
            self.status.set("已打开打印。双面打印需要在打印窗口里选择“双面打印”。")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"打开打印失败：{exc}")


if __name__ == "__main__":
    App().mainloop()
