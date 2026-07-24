"""Annotate QA screenshots and assemble them into a small animated demo reel.

Three subcommands:

- ``annotate``: append a caption bar (step label + PASS/FAIL/INFO chip) below a
  screenshot and optionally draw highlight boxes around the regions that matter.
  Highlight coordinates are CSS pixels from ``getBoundingClientRect()``; pass
  ``--viewport-width`` so they scale correctly on HiDPI captures.
- ``animate``: stitch ordered (annotated) frames into an animated WebP, with an
  optional GIF fallback. WebP keeps full 24-bit color and is typically several
  times smaller than a palette GIF at the same readability.
- ``video``: transcode a recorded demo-pass session (WebM from the browser
  tool's video recording) into a compact H.264 MP4. Requires ``ffmpeg``.

Runs with the repo's existing Pillow dependency via ``uv run python`` from the
PostHog repo root. MP4 output shells out to a locally installed ``ffmpeg``; all
other paths need no extra dependencies. No network access.

Annotation styling follows PostHog product color tokens (``frontend/src/styles/
base.scss``): brand red ``#f54e00`` highlights, ``--success``/``--danger`` chips,
brand black bar with cream text.
"""

from __future__ import annotations

import sys
import shutil
import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont

# keep in sync with the colors in scripts/cursor-overlay.js
BAR_BG = (21, 21, 21)
BAR_TEXT = (238, 239, 233)
CHIP_TEXT = (255, 255, 255)
CHIP_COLORS = {
    "pass": (56, 134, 0),
    "fail": (219, 55, 7),
    "info": (29, 74, 255),
}
HIGHLIGHT_COLOR = (245, 78, 0)
HIGHLIGHT_WIDTH = 4
HIGHLIGHT_PADDING = 6
MAX_ANIMATION_WIDTH = 1200
DEFAULT_FRAME_MS = 1800

FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


@dataclass
class Frame:
    path: Path
    duration_ms: int


def _load_font(size: int) -> FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: FreeTypeFont | ImageFont.ImageFont) -> int:
    return int(draw.textlength(text, font=font))


def _wrap_caption(
    draw: ImageDraw.ImageDraw, text: str, font: FreeTypeFont | ImageFont.ImageFont, max_width: int
) -> list[str]:
    if _text_width(draw, text, font) <= max_width:
        return [text]
    words = []
    for word in text.split():
        # a single token wider than the bar (URL, selector, id) is chunked by
        # characters, otherwise the greedy wrap would let it overflow the image
        while _text_width(draw, word, font) > max_width and len(word) > 1:
            cut = len(word)
            while cut > 1 and _text_width(draw, word[:cut], font) > max_width:
                cut -= 1
            words.append(word[:cut])
            word = word[cut:]
        words.append(word)
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > 2:
        truncated = lines[1]
        while truncated and _text_width(draw, f"{truncated}…", font) > max_width:
            truncated = truncated[:-1].rstrip()
        lines = [lines[0], f"{truncated}…"]
    return lines


def _parse_rect(value: str) -> tuple[float, float, float, float]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"highlight must be X,Y,W,H (got {value!r})")
    try:
        x, y, w, h = (float(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"highlight must be numeric X,Y,W,H (got {value!r})") from exc
    return x, y, w, h


def _parse_point(value: str) -> tuple[float, float]:
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"click must be X,Y (got {value!r})")
    try:
        x, y = (float(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"click must be numeric X,Y (got {value!r})") from exc
    return x, y


def _draw_cursor(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    ring = 16
    draw.ellipse((x - ring, y - ring, x + ring, y + ring), outline=HIGHLIGHT_COLOR, width=3)
    arrow = [
        (x, y),
        (x, y + 17),
        (x + 4.5, y + 13),
        (x + 8, y + 20.5),
        (x + 11, y + 19),
        (x + 7.5, y + 11.5),
        (x + 13.5, y + 11),
    ]
    draw.polygon(arrow, fill=(255, 255, 255), outline=(21, 21, 21), width=2)


def annotate(args: argparse.Namespace) -> int:
    image = Image.open(args.input).convert("RGB")
    width, height = image.size
    scale = width / args.viewport_width if args.viewport_width else 1.0

    draw = ImageDraw.Draw(image)
    for x, y, w, h in args.highlight:
        left = max(0, int(x * scale) - HIGHLIGHT_PADDING)
        top = max(0, int(y * scale) - HIGHLIGHT_PADDING)
        right = min(width - 1, int((x + w) * scale) + HIGHLIGHT_PADDING)
        bottom = min(height - 1, int((y + h) * scale) + HIGHLIGHT_PADDING)
        if right <= left or bottom <= top:
            sys.stderr.write(f"warning: highlight {x},{y},{w},{h} is outside the image, skipped\n")
            continue
        draw.rounded_rectangle((left, top, right, bottom), radius=8, outline=HIGHLIGHT_COLOR, width=HIGHLIGHT_WIDTH)

    for x, y in args.click:
        _draw_cursor(draw, int(x * scale), int(y * scale))

    bar_height = max(48, width // 22)
    font = _load_font(int(bar_height * 0.42))
    chip_label = args.status.upper()
    caption = f"Step {args.step} · {args.caption}" if args.step else args.caption

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    chip_text_w = _text_width(measure, chip_label, font)
    chip_pad_x = bar_height // 3
    chip_w = chip_text_w + 2 * chip_pad_x
    margin = bar_height // 3
    caption_max_w = max(width - chip_w - 3 * margin, bar_height)
    lines = _wrap_caption(measure, caption, font, caption_max_w)
    line_height = int(bar_height * 0.52)
    total_bar_h = bar_height if len(lines) == 1 else bar_height + line_height

    annotated = Image.new("RGB", (width, height + total_bar_h), BAR_BG)
    annotated.paste(image, (0, 0))
    draw = ImageDraw.Draw(annotated)

    chip_h = int(bar_height * 0.62)
    chip_top = height + (total_bar_h - chip_h) // 2
    draw.rounded_rectangle(
        (margin, chip_top, margin + chip_w, chip_top + chip_h),
        radius=chip_h // 2,
        fill=CHIP_COLORS[args.status],
    )
    bbox = font.getbbox(chip_label)
    text_h = bbox[3] - bbox[1]
    draw.text(
        (margin + chip_pad_x, chip_top + (chip_h - text_h) // 2 - bbox[1]),
        chip_label,
        font=font,
        fill=CHIP_TEXT,
    )

    text_x = margin * 2 + chip_w
    text_block_h = line_height * len(lines)
    text_y = height + (total_bar_h - text_block_h) // 2
    for line in lines:
        line_bbox = font.getbbox(line)
        draw.text(
            (text_x, text_y - line_bbox[1] + (line_height - (line_bbox[3] - line_bbox[1])) // 2),
            line,
            font=font,
            fill=BAR_TEXT,
        )
        text_y += line_height

    output = args.output or args.input.with_suffix(".annotated.png")
    annotated.save(output, format="PNG", optimize=True)
    sys.stdout.write(f"{output}\n")
    return 0


def _parse_frame(value: str) -> Frame:
    path_part, sep, duration_part = value.rpartition(":")
    if sep and duration_part.isdigit():
        return Frame(Path(path_part), int(duration_part))
    return Frame(Path(value), DEFAULT_FRAME_MS)


def animate(args: argparse.Namespace) -> int:
    frames: list[Frame] = args.frame
    missing = [f.path for f in frames if not f.path.is_file()]
    if missing:
        raise SystemExit(f"missing frame file(s): {', '.join(str(p) for p in missing)}")
    if len(frames) < 2:
        raise SystemExit("need at least 2 frames for an animation; use the still screenshot instead")

    images = [Image.open(f.path).convert("RGB") for f in frames]
    target_w = min(args.max_width, max(img.width for img in images))
    resized: list[Image.Image] = []
    for img in images:
        # only downscale oversized frames; narrower ones are padded below so
        # readable text never gets blurred by upscaling
        if img.width > target_w:
            img = img.resize((target_w, round(img.height * target_w / img.width)), Image.LANCZOS)
        resized.append(img)

    max_h = max(img.height for img in resized)
    padded: list[Image.Image] = []
    for img in resized:
        if img.width != target_w or img.height != max_h:
            # anchor at the bottom so every frame's caption bar sits at the same
            # place; the padding goes above the screenshot, not below it
            canvas = Image.new("RGB", (target_w, max_h), BAR_BG)
            canvas.paste(img, ((target_w - img.width) // 2, max_h - img.height))
            img = canvas
        padded.append(img)

    durations = [f.duration_ms for f in frames]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    padded[0].save(
        args.output,
        format="WEBP",
        save_all=True,
        append_images=padded[1:],
        duration=durations,
        loop=0,
        quality=82,
        method=6,
    )
    outputs = [args.output]
    if args.gif:
        padded[0].save(
            args.gif,
            format="GIF",
            save_all=True,
            append_images=padded[1:],
            duration=durations,
            loop=0,
            optimize=True,
        )
        outputs.append(args.gif)

    for path in outputs:
        sys.stdout.write(f"{path} ({path.stat().st_size / 1024:.0f} KB)\n")
    return 0


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg not found on PATH; MP4 output needs a local ffmpeg install")
    return ffmpeg


def _run_ffmpeg(ffmpeg_args: list[str]) -> None:
    result = subprocess.run(ffmpeg_args, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg failed:\n{result.stderr[-2000:]}")


def video(args: argparse.Namespace) -> int:
    if not args.input.is_file():
        raise SystemExit(f"missing input recording: {args.input}")
    ffmpeg = _require_ffmpeg()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # -ss after -i: output seeking is frame-accurate; input seeking snaps to the
    # sparse keyframes of screencast WebMs and silently shifts the window
    trim = ["-ss", f"{args.trim_start:.3f}"] if args.trim_start else []
    _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-i",
            str(args.input),
            *trim,
            "-vf",
            f"scale='trunc(min({args.max_width},iw)/2)*2':-2,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-an",
            "-movflags",
            "+faststart",
            str(args.output),
        ]
    )
    sys.stdout.write(f"{args.output} ({args.output.stat().st_size / 1024:.0f} KB)\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    annotate_parser = subparsers.add_parser("annotate", help="caption and highlight one screenshot")
    annotate_parser.add_argument("--input", type=Path, required=True, help="source screenshot (PNG)")
    annotate_parser.add_argument("--caption", required=True, help="what is happening in this frame")
    annotate_parser.add_argument("--step", type=int, help="step number shown before the caption")
    annotate_parser.add_argument(
        "--status", choices=sorted(CHIP_COLORS), default="info", help="chip rendered next to the caption"
    )
    annotate_parser.add_argument(
        "--highlight",
        type=_parse_rect,
        action="append",
        default=[],
        metavar="X,Y,W,H",
        help="CSS-pixel rect to outline, from getBoundingClientRect(); repeatable",
    )
    annotate_parser.add_argument(
        "--click",
        type=_parse_point,
        action="append",
        default=[],
        metavar="X,Y",
        help="CSS-pixel point where an interaction happened; draws a cursor with a ripple ring; repeatable",
    )
    annotate_parser.add_argument(
        "--viewport-width",
        type=float,
        help="window.innerWidth at capture time, to scale highlight/click coords on HiDPI screenshots",
    )
    annotate_parser.add_argument("--output", type=Path, help="output path (default: <input>.annotated.png)")
    annotate_parser.set_defaults(func=annotate)

    animate_parser = subparsers.add_parser("animate", help="assemble frames into an animated WebP")
    animate_parser.add_argument(
        "--frame",
        type=_parse_frame,
        action="append",
        required=True,
        metavar="PATH[:DURATION_MS]",
        help=f"ordered frame with optional per-frame duration (default {DEFAULT_FRAME_MS} ms); repeatable",
    )
    animate_parser.add_argument("--output", type=Path, required=True, help="animated WebP output path")
    animate_parser.add_argument("--gif", type=Path, help="also write a GIF fallback to this path")
    animate_parser.add_argument("--max-width", type=int, default=MAX_ANIMATION_WIDTH, help="cap frame width")
    animate_parser.set_defaults(func=animate)

    video_parser = subparsers.add_parser("video", help="transcode a session recording (WebM) to H.264 MP4")
    video_parser.add_argument("--input", type=Path, required=True, help="source recording, e.g. WebM from browser MCP")
    video_parser.add_argument("--output", type=Path, required=True, help="MP4 output path")
    video_parser.add_argument("--max-width", type=int, default=1280, help="cap output width")
    video_parser.add_argument(
        "--trim-start", type=float, default=0.0, help="drop this many seconds of lead-in from the recording"
    )
    video_parser.set_defaults(func=video)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
