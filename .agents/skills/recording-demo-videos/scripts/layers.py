"""The camera and overlay pass for a storyboard with zooms.

The page is recorded without captions or stickers. This pass zooms the camera toward the steps that ask for it, then
draws the captions and stickers over the zoomed frame, so they stay put while the page moves under them.
Every time in the timeline is in seconds of the recording clock.
"""

import io
import math
import subprocess
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

from PIL import Image
from playwright.sync_api import sync_playwright

# A zoom frames its target to fill about this share of the view, within these levels.
ZOOM_FILL = 0.55
ZOOM_MIN, ZOOM_MAX = 1.25, 2.0
# The camera eases toward its target with this time constant, in seconds.
CAMERA_EASE = 0.45
# A click zoom stays this long after the action. The page usually changes after a click.
ZOOM_AFTER_ACTION = 0.6


def render_overlays(
    rd: ModuleType, brand: Any, timeline: dict[str, Any], viewport: dict[str, int], out_width: int
) -> tuple[dict[str, tuple[Image.Image, tuple[int, int]]], list[dict[str, Any]]]:
    """Caption and sticker images at the output size, from the same HTML and CSS as the in-page overlay."""
    scale = out_width / viewport["width"]
    dark, cream, accent = brand.colors["dark"], brand.colors["cream"], brand.colors["tangerine"]
    captions: dict[str, tuple[Image.Image, tuple[int, int]]] = {}
    stickers: list[dict[str, Any]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=viewport, device_scale_factor=scale)
        for caption in timeline["captions"]:
            text = caption["text"]
            if not text or text in captions:
                continue
            page.set_content(
                f"""<!doctype html><html><head><style>{brand.font_css} html,body{{margin:0;background:transparent}}
#c{{position:fixed;left:50%;bottom:32px;transform:translateX(-50%);max-width:1080px;padding:14px 24px;border-radius:10px;
border-left:6px solid {accent};background:{dark}ee;color:{cream};font:700 21px/1.35 RoundHog,-apple-system,Inter,sans-serif;
box-shadow:0 10px 30px rgba(0,0,0,.25)}}</style></head><body><div id="c"></div></body></html>"""
            )
            page.evaluate("t => { document.getElementById('c').textContent = t }", text)
            page.evaluate("document.fonts.ready")
            image = Image.open(io.BytesIO(page.screenshot(omit_background=True))).convert("RGBA")
            box = image.getbbox()
            if box:
                captions[text] = (image.crop(box), (box[0], box[1]))
        for sticker in timeline["stickers"]:
            position = rd.STICKER_POSITIONS.get(
                sticker.get("position", "bottom-right"), rd.STICKER_POSITIONS["bottom-right"]
            )
            label = (
                f'<div id="l" style="background:{accent};color:#fff;font:800 22px RoundHog,-apple-system,sans-serif;'
                'padding:6px 16px;border-radius:999px;transform:rotate(-4deg);box-shadow:0 6px 16px rgba(0,0,0,.2)"></div>'
                if sticker.get("text")
                else ""
            )
            page.set_content(
                f"""<!doctype html><html><head><style>{brand.font_css} html,body{{margin:0;background:transparent}}</style>
</head><body><div id="s" style="position:fixed;{position};display:flex;flex-direction:column;align-items:center;gap:6px;
padding:16px"><img src="{brand.hog(sticker.get("hog", "star"))}" style="width:190px;height:190px;object-fit:contain;
filter:drop-shadow(0 8px 14px rgba(0,0,0,.22))">{label}</div></body></html>"""
            )
            if sticker.get("text"):
                page.evaluate("t => { document.getElementById('l').textContent = t }", sticker["text"])
            page.evaluate("document.fonts.ready")
            element = page.locator("#s")
            box = element.bounding_box() or {"x": 0, "y": 0, "width": 0, "height": 0}
            stickers.append(
                {
                    **sticker,
                    "image": Image.open(io.BytesIO(element.screenshot(omit_background=True))).convert("RGBA"),
                    "cx": (box["x"] + box["width"] / 2) * scale,
                    "cy": (box["y"] + box["height"] / 2) * scale,
                }
            )
        browser.close()
    return captions, stickers


def _ease_out_back(t: float, s: float = 1.7) -> float:
    t -= 1
    return t * t * ((s + 1) * t + s) + 1


def _sticker_frame(sticker: dict[str, Any], t: float) -> tuple[Image.Image, int, int] | None:
    """The sticker at time t: it pops in, holds, then shrinks away. Matches the in-page sticker."""
    u = t - sticker["at"]
    seconds = sticker.get("seconds", 3)
    if u < 0 or u > seconds + 0.35:
        return None
    if u < 0.42:
        k = _ease_out_back(u / 0.42)
        scale, angle, alpha = 0.2 + 0.8 * k, -14 + 19 * k, min(u / 0.2, 1)
    elif u < seconds:
        scale, angle, alpha = 1.0, 5.0, 1.0
    else:
        k = (u - seconds) / 0.3
        scale, angle, alpha = 1 - 0.4 * k, 5 + 7 * k, max(1 - k, 0)
    image = sticker["image"]
    resized = image.resize((max(int(image.width * scale), 1), max(int(image.height * scale), 1)), Image.BICUBIC)
    rotated = resized.rotate(-angle, Image.BICUBIC, expand=True)
    if alpha < 1:
        rotated.putalpha(rotated.getchannel("A").point(lambda value: int(value * alpha)))
    return rotated, int(sticker["cx"] - rotated.width / 2), int(sticker["cy"] - rotated.height / 2)


def compose(
    rd: ModuleType,
    brand: Any,
    frames: Iterable[tuple[float, Image.Image]],
    timeline: dict[str, Any],
    viewport: dict[str, int],
    out_width: int,
    fps: int,
    output: Path,
) -> None:
    """Zoom, then draw the overlays, frame by frame, and encode the result.

    `frames` gives the time of each frame that goes into the video and the frame itself, in page coordinates at any
    scale. The camera moves only on these frames, so a zoom never finishes inside a cut and jumps.
    """
    vw, vh = viewport["width"], viewport["height"]
    out_h = round(out_width * vh / vw / 2) * 2
    captions, stickers = render_overlays(rd, brand, timeline, viewport, out_width)
    encoder = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_width}x{out_h}",
         "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(output)],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    assert encoder.stdin is not None
    cards, zooms = timeline["cards"], timeline["zooms"]
    caption_events = timeline["captions"]
    ease = 1 - math.exp(-(1 / fps) / CAMERA_EASE)
    z, cx, cy = 1.0, vw / 2, vh / 2
    for t, frame in frames:
        on_card = any(card["from"] <= t < card["to"] for card in cards)
        active = next((zoom for zoom in zooms if zoom["from"] <= t <= zoom["to"]), None)
        if active and not on_card:
            box = active["box"]
            fill = min(vw * ZOOM_FILL / max(box["width"], 1), vh * ZOOM_FILL / max(box["height"], 1))
            target_z = active["level"] or min(max(fill, ZOOM_MIN), ZOOM_MAX)
            tx, ty = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        else:
            target_z, tx, ty = 1.0, vw / 2, vh / 2
        z += (target_z - z) * ease
        cx += (tx - cx) * ease
        cy += (ty - cy) * ease
        if on_card:
            # A card is a scene change, so the next page starts from the full view.
            z, cx, cy = 1.0, vw / 2, vh / 2
        w, h = vw / z, vh / z
        left = min(max(cx - w / 2, 0), vw - w)
        top = min(max(cy - h / 2, 0), vh - h)
        k = frame.width / vw
        if z > 1.001 or frame.size != (out_width, out_h):
            # A fractional box resamples the frame, so a slow zoom or pan never steps by whole pixels. Outside a zoom,
            # a frame already at the output size needs no resampling, which keeps the pass quick.
            box = (left * k, top * k, (left + w) * k, (top + h) * k)
            frame = frame.resize((out_width, out_h), Image.LANCZOS, box=box)
        shown = [event for event in caption_events if event["at"] <= t]
        if shown and shown[-1]["text"] in captions and not on_card:
            image, at = captions[shown[-1]["text"]]
            fade = min((t - shown[-1]["at"]) / 0.15, 1)
            if fade < 1:
                image = image.copy()
                image.putalpha(image.getchannel("A").point(lambda value, f=fade: int(value * f)))
            frame.paste(image, at, image)
        for sticker in stickers:
            drawn = _sticker_frame(sticker, t)
            if drawn:
                frame.paste(drawn[0], (drawn[1], drawn[2]), drawn[0])
        encoder.stdin.write(frame.tobytes())
    encoder.stdin.close()
    encoder.wait()
