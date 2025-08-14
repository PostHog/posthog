from typing import Literal, Optional
import os
import tempfile
import time
import uuid
import shutil
import subprocess
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import posthoganalytics
from posthog.exceptions_capture import capture_exception

ScreenWidth = Literal[800, 1920, 1400]
HEIGHT_OFFSET = 85


def record_replay_to_file(
    image_path: str,
    url_to_render: str,
    screenshot_width: ScreenWidth,
    wait_for_css_selector: str,
    screenshot_height: int = 600,
) -> None:
    temp_dir_ctx: Optional[tempfile.TemporaryDirectory] = None
    try:
        temp_dir_ctx = tempfile.TemporaryDirectory(prefix="ph-video-export-")
        record_dir = temp_dir_ctx.name
        with sync_playwright() as p:
            headless = os.getenv("EXPORTER_HEADLESS", "1") != "0"
            browser = p.chromium.launch(
                headless=headless,
                devtools=not headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--use-gl=swiftshader",
                    "--disable-software-rasterizer",
                    "--force-device-scale-factor=2",
                ],
            )
            width = int(screenshot_width)
            height = int(screenshot_height)
            context = browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=record_dir,
                record_video_size={"width": width, "height": height},
            )
            page = context.new_page()
            record_started = time.monotonic()
            try:
                page.goto(url_to_render, wait_until="load", timeout=30000)
            except PlaywrightTimeoutError:
                pass
            try:
                page.wait_for_selector(wait_for_css_selector, state="visible", timeout=20000)
            except PlaywrightTimeoutError:
                pass
            try:
                page.wait_for_selector(".Spinner", state="detached", timeout=20000)
            except PlaywrightTimeoutError:
                pass
            try:
                final_height = page.evaluate(
                    "() => { const el = document.querySelector('.replayer-wrapper'); if (el) { const r = el.getBoundingClientRect(); return Math.max(r.height, document.body.scrollHeight);} return document.body.scrollHeight; }"
                )
                final_width = (
                    page.evaluate(
                        "() => { const r = document.querySelector('.replayer-wrapper'); if (r) return r.offsetWidth || 0; const t = document.querySelector('table'); if (t) return Math.floor((t.offsetWidth || 0) * 1.5); return 0; }"
                    )
                    or width
                )
                final_width = max(width, min(1800, int(final_width)))
                page.set_viewport_size({"width": final_width, "height": int(final_height) + HEIGHT_OFFSET})
            except Exception:
                pass
            ready_at = time.monotonic()
            page.wait_for_timeout(500)
            page.wait_for_timeout(5000)
            video = page.video
            page.close()
            pre_roll = max(0.0, ready_at - record_started)
            tmp_webm = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.webm")
            if hasattr(video, "save_as"):
                video.save_as(tmp_webm)
            else:
                src = video.path()
                if not src:
                    raise RuntimeError("Playwright did not provide a video path.")
                shutil.move(src, tmp_webm)
            try:
                ext = os.path.splitext(image_path)[1].lower()
                if ext == ".mp4":
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-ss",
                            f"{pre_roll:.2f}",
                            "-i",
                            tmp_webm,
                            "-t",
                            "5.00",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "veryfast",
                            "-crf",
                            "23",
                            "-pix_fmt",
                            "yuv420p",
                            "-movflags",
                            "+faststart",
                            "-f",
                            "mp4",
                            image_path,
                        ],
                        check=True,
                    )
                elif ext == ".gif":
                    vf = f"fps=12,scale={final_width}:-2:flags=lanczos" if "final_width" in locals() else "fps=12"
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-ss",
                            f"{pre_roll:.2f}",
                            "-t",
                            "5.00",
                            "-i",
                            tmp_webm,
                            "-vf",
                            f"{vf},split[s0][s1];[s0]palettegen=stats_mode=single[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                            "-loop",
                            "0",
                            "-f",
                            "gif",
                            image_path,
                        ],
                        check=True,
                    )
                else:
                    shutil.move(tmp_webm, image_path)
            finally:
                try:
                    context.close()
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        with posthoganalytics.new_context():
            posthoganalytics.tag("url_to_render", url_to_render)
            posthoganalytics.tag("video_target_path", image_path)
            capture_exception(e)
        raise
    finally:
        if temp_dir_ctx:
            try:
                temp_dir_ctx.cleanup()
            except Exception:
                pass
