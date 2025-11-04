import os
import time
import uuid
import shutil
import tempfile
import subprocess
from typing import Optional

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception

from playwright.sync_api import (
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

logger = structlog.get_logger(__name__)

HEIGHT_OFFSET = 85
PLAYBACK_SPEED_MULTIPLIER = 4  # Speed up playback during recording for long videos
DURATION_THRESHOLD_FOR_SPEED_UP = 15


def _wait_for_page_ready(page: Page, url_to_render: str, wait_for_css_selector: str) -> None:
    """Helper function to wait for page to be ready for recording."""
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


def _convert_to_mp4(
    tmp_webm: str, image_path: str, pre_roll: float, recording_duration: int, playback_speed: int
) -> None:
    """Convert WebM to MP4 using ffmpeg."""
    # Slow down video if it was recorded at high speed
    video_filter = f"setpts={playback_speed}*PTS" if playback_speed > 1.0 else None
    cmd = [
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
        f"{float(recording_duration):.2f}",
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
    ]
    if video_filter:
        cmd.extend(["-vf", video_filter])
    cmd.append(image_path)

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        error_msg = f"ffmpeg failed with exit code {e.returncode}"
        if e.stderr:
            error_msg += f": {e.stderr.strip()}"
        raise RuntimeError(error_msg) from e


def _convert_to_gif(
    tmp_webm: str, image_path: str, pre_roll: float, recording_duration: int, measured_width: Optional[int]
) -> None:
    """Convert WebM to GIF using ffmpeg."""
    vf_parts = ["fps=12"]
    if measured_width is not None:
        vf_parts.append(f"scale={measured_width}:-2:flags=lanczos")
    vf = ",".join(vf_parts)

    try:
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
                f"{float(recording_duration):.2f}",
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
    except subprocess.CalledProcessError as e:
        error_msg = f"ffmpeg failed with exit code {e.returncode}"
        if e.stderr:
            error_msg += f": {e.stderr.strip()}"
        raise RuntimeError(error_msg) from e


def _scale_dimensions_if_needed(width: int, height: int, max_size: int = 1400) -> tuple[int, int]:
    """Scale down dimensions while maintaining aspect ratio if either dimension exceeds max_size."""
    if width <= max_size and height <= max_size:
        return width, height

    # Determine which dimension is larger and scale based on that
    if width > height:
        # Width is larger, scale based on width
        scale_factor = max_size / width
        scaled_width = max_size
        scaled_height = int(height * scale_factor)
    else:
        # Height is larger (or equal), scale based on height
        scale_factor = max_size / height
        scaled_width = int(width * scale_factor)
        scaled_height = max_size

    logger.info(
        "video_exporter.dimensions_scaled",
        original_width=width,
        original_height=height,
        scaled_width=scaled_width,
        scaled_height=scaled_height,
        scale_factor=scale_factor,
    )

    return scaled_width, scaled_height


def detect_recording_resolution(
    browser: Browser,
    url_to_render: str,
    wait_for_css_selector: str,
    default_width: int,
    default_height: int,
) -> tuple[int, int]:
    logger.info("video_exporter.resolution_detection_start")

    # Create temporary context just for resolution detection
    context = browser.new_context(
        viewport={"width": default_width, "height": default_height},
    )
    page = context.new_page()

    try:
        # Navigate and wait for player to load
        _wait_for_page_ready(page, url_to_render, wait_for_css_selector)

        # Wait for resolution to be available from sessionRecordingPlayerLogic global variable
        try:
            logger.info("video_exporter.waiting_for_resolution_global")
            resolution = page.wait_for_function(
                """
                () => {
                  const r = (window).__POSTHOG_RESOLUTION__;
                  if (!r) return false;
                  const w = Number(r.width), h = Number(r.height);
                  return (w > 0 && h > 0) ? {width: w, height: h} : false;
                }
                """,
                timeout=15000,
            ).json_value()

            detected_width = int(resolution["width"])
            detected_height = int(resolution["height"])
            logger.info("video_exporter.resolution_detected", width=detected_width, height=detected_height)
            return detected_width, detected_height

        except Exception as e:
            logger.warning("video_exporter.resolution_detection_failed", error=str(e))
            return default_width, default_height

    finally:
        # Clean up detection context
        page.close()
        context.close()
        logger.info("video_exporter.resolution_detection_complete")


def record_replay_to_file(
    image_path: str,
    url_to_render: str,
    screenshot_width: Optional[int],
    wait_for_css_selector: str,
    screenshot_height: Optional[int],
    recording_duration: int = 5,  # Duration in seconds
) -> None:
    # Input validation
    if recording_duration <= 0:
        raise ValueError("recording_duration must be positive")
    if screenshot_width is not None and screenshot_width <= 0:
        raise ValueError("screenshot_width must be positive")
    if screenshot_height is not None and screenshot_height <= 0:
        raise ValueError("screenshot_height must be positive")

    # Check if ffmpeg is available for video conversion
    ext = os.path.splitext(image_path)[1].lower()
    if ext in [".mp4", ".gif"] and not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required for MP4 and GIF exports but was not found in PATH")

    temp_dir_ctx: Optional[tempfile.TemporaryDirectory] = None
    try:
        temp_dir_ctx = tempfile.TemporaryDirectory(prefix="ph-video-export-", ignore_cleanup_errors=True)
        record_dir = temp_dir_ctx.name
        with sync_playwright() as p:
            headless = os.getenv("EXPORTER_HEADLESS", "1") != "0"  # TIP: for debugging, set to False
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

            # Check if dimensions were provided or need to be detected
            if screenshot_width is not None and screenshot_height is not None:
                # Use provided dimensions
                width = screenshot_width
                height = screenshot_height
                logger.info("video_exporter.using_provided_dimensions", width=width, height=height)
            else:
                # Phase 1: Detect actual recording resolution
                default_width = 1400  # Default fallback
                default_height = 600  # Default fallback

                width, height = detect_recording_resolution(
                    browser=browser,
                    url_to_render=url_to_render,
                    wait_for_css_selector=wait_for_css_selector,
                    default_width=default_width,
                    default_height=default_height,
                )
                logger.info("video_exporter.using_detected_dimensions", width=width, height=height)

            # Scale dimensions if needed to fit within max width while maintaining aspect ratio
            width, height = _scale_dimensions_if_needed(width, height)

            # Phase 2: Create recording context with exact resolution
            context = browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=record_dir,
                record_video_size={"width": width, "height": height},
            )
            page = context.new_page()
            record_started = time.monotonic()
            logger.info("video_exporter.recording_context_created", width=width, height=height)

            # Navigate with correct dimensions
            _wait_for_page_ready(page, url_to_render, wait_for_css_selector)
            measured_width: Optional[int] = None
            try:
                dimensions = page.evaluate("""
                    () => {
                        const replayer = document.querySelector('.replayer-wrapper');
                        if (replayer) {
                            const rect = replayer.getBoundingClientRect();
                            return {
                                height: Math.max(rect.height, document.body.scrollHeight),
                                width: replayer.offsetWidth || 0
                            };
                        }
                        // Fallback for tables if no replayer
                        const table = document.querySelector('table');
                        return {
                            height: document.body.scrollHeight,
                            width: table ? Math.floor((table.offsetWidth || 0) * 1.5) : 0
                        };
                    }
                """)
                final_height = dimensions["height"]
                width_candidate = dimensions["width"] or width
                measured_width = max(width, min(1800, int(width_candidate)))
                page.set_viewport_size({"width": measured_width, "height": int(final_height) + HEIGHT_OFFSET})
            except Exception as e:
                logger.warning("video_exporter.viewport_resize_failed", error=str(e))
            ready_at = time.monotonic()
            page.wait_for_timeout(500)

            # Speed up playback for long MP4 recordings to reduce recording time
            ext = os.path.splitext(image_path)[1].lower()
            playback_speed = PLAYBACK_SPEED_MULTIPLIER if (ext == ".mp4" and recording_duration > 15) else 1
            # Record for actual_duration (shorter if sped up)
            actual_duration = recording_duration / playback_speed
            page.wait_for_timeout(int(actual_duration * 1000))
            video = page.video
            page.close()
            if video is None:
                raise RuntimeError("Playwright did not produce a video. Ensure record_video_dir is set.")

            pre_roll = max(0.0, ready_at - record_started)
            tmp_webm = os.path.join(record_dir, f"{uuid.uuid4()}.webm")
            if hasattr(video, "save_as"):
                video.save_as(tmp_webm)
            else:
                src = video.path()
                if not src:
                    raise RuntimeError("Playwright did not provide a video path.")
                shutil.move(src, tmp_webm)
            try:
                if ext == ".mp4":
                    _convert_to_mp4(tmp_webm, image_path, pre_roll, recording_duration, playback_speed)
                elif ext == ".gif":
                    _convert_to_gif(tmp_webm, image_path, pre_roll, recording_duration, measured_width)
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
            temp_dir_ctx.cleanup()
