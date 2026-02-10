import os
import abc
import json
import time
import uuid
import shutil
import tempfile
import subprocess
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import structlog
import posthoganalytics
from playwright.sync_api import (
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from posthog.schema import ReplayInactivityPeriod

from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

HEIGHT_OFFSET = 85
PLAYBACK_SPEED_MULTIPLIER = 4  # Speed up playback during recording for long videos


@dataclass(frozen=True)
class RecordingResult:
    """Result from the Node.js recording script."""

    video_path: str
    pre_roll: float
    playback_speed: int
    measured_width: Optional[int]
    inactivity_periods: list[ReplayInactivityPeriod] | None
    segment_start_timestamps: dict[float, float]
    custom_fps: int | None = None


@dataclass(frozen=True)
class RecordReplayToFileOptions:
    image_path: str
    url_to_render: str
    wait_for_css_selector: str
    # Recording duration in seconds.
    recording_duration: int
    screenshot_width: Optional[int] = None
    screenshot_height: Optional[int] = None
    playback_speed: int = 1
    use_puppeteer: bool = False

    def __post_init__(self) -> None:
        if self.recording_duration <= 0:
            raise ValueError("recording_duration must be positive")
        if self.screenshot_width is not None and self.screenshot_width <= 0:
            raise ValueError("screenshot_width must be positive")
        if self.screenshot_height is not None and self.screenshot_height <= 0:
            raise ValueError("screenshot_height must be positive")
        if not (1 <= self.playback_speed <= 360):
            raise ValueError(f"playback_speed must be between 1 and 360, got {self.playback_speed}")


class _ReplayVideoRecorder(abc.ABC):
    """Base class for recording a replay to a file."""

    RECORDING_BUFFER_SECONDS = 120  # How long we expect it would take for recording to start playing

    def __init__(
        self,
        output_path: str,
        record_dir: str,
        opts: RecordReplayToFileOptions,
    ):
        self.output_path = output_path
        self.record_dir = record_dir
        self.opts = opts

    @abc.abstractmethod
    def record(self) -> RecordingResult:
        """Record a replay to a file."""
        raise NotImplementedError


class PuppeteerRecorder(_ReplayVideoRecorder):
    """Record a replay to a file using Puppeteer."""

    # Path to Node.js scripts directory (relative to project root)
    # TODO: Find a better way to do this
    NODEJS_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "nodejs", "src", "scripts")
    SCRIPT_NAME = "record-replay-session-to-video-puppeteer.js"

    def record(self) -> RecordingResult:
        # Load the script
        script_path = os.path.join(self.NODEJS_SCRIPTS_DIR, self.SCRIPT_NAME)
        if not os.path.exists(script_path):
            msg = f"Puppeteer recorder script not found: {script_path}"
            logger.exception(
                msg,
                options=asdict(self.opts),
                signals_type="video_export",
            )
            raise FileNotFoundError(msg)
        # Build input
        options = {
            "url_to_render": self.opts.url_to_render,
            "output_path": self.output_path,
            "wait_for_css_selector": self.opts.wait_for_css_selector,
            "recording_duration": self.opts.recording_duration,
            "playback_speed": self.opts.playback_speed,
            "headless": os.getenv("EXPORTER_HEADLESS", "1") != "0",
        }
        if self.opts.screenshot_width is not None:
            options["screenshot_width"] = self.opts.screenshot_width
        if self.opts.screenshot_height is not None:
            options["screenshot_height"] = self.opts.screenshot_height
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            options["ffmpeg_path"] = ffmpeg_path
        else:
            msg = "ffmpeg not found in PATH"
            logger.exception(msg, signals_type="video_export")
            raise RuntimeError(msg)
        options_json = json.dumps(options)
        # Record the video
        try:
            result = subprocess.run(
                ["node", script_path, options_json],
                capture_output=True,
                text=True,
                check=False,  # Don't raise on non-zero exit, we'll check the JSON output
                timeout=60 * 60 * 3,  # 3 hours timeout in case of script hanging, as it has own timeouts
            )
            # Parse JSON output from stdout
            if not result.stdout.strip():
                msg = "Puppeteer recorder produced no output when recording the session."
                logger.exception(
                    msg,
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    options=options,
                    signals_type="video_export",
                )
                raise RuntimeError(msg)
            try:
                output = json.loads(result.stdout.strip())
            except json.JSONDecodeError as e:
                msg = (
                    f"Failed to parse Puppeteer output, when recording the session: {e}. Output: {result.stdout[:500]}"
                )
                logger.exception(
                    msg,
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    options=options,
                    signals_type="video_export",
                )
                raise RuntimeError(msg) from e
            if not output.get("success"):
                msg = f"Puppeteer recorder failed, when recording the session: {output.get('error', 'Unknown error')}"
                logger.exception(
                    msg,
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    options=options,
                    signals_type="video_export",
                )
                raise RuntimeError(msg)
            # Parse inactivity periods
            if not output.get("inactivity_periods"):
                # Expect that all the recordings should have at least one period with active: True/False
                msg = "Puppeteer recorder produced no inactivity periods when recording the session."
                err = RuntimeError(msg)
                logger.exception(msg, output=output, options=options, signals_type="video_export")
                capture_exception(err, additional_properties={"options": options, "output": output})
                raise err
            inactivity_periods = [
                ReplayInactivityPeriod.model_validate(period) for period in output["inactivity_periods"]
            ]
            # Parse segment timestamps
            segment_start_timestamps = {}
            if output.get("segment_start_timestamps"):
                segment_start_timestamps = {float(k): float(v) for k, v in output["segment_start_timestamps"].items()}
            # Return the result
            return RecordingResult(
                video_path=output["video_path"],
                pre_roll=output["pre_roll"],
                playback_speed=output["playback_speed"],
                measured_width=output.get("measured_width"),
                inactivity_periods=inactivity_periods,
                segment_start_timestamps=segment_start_timestamps,
                custom_fps=output.get("custom_fps"),
            )
        except Exception as e:
            msg = f"Puppeteer recorder failed, when recording the session: {e}"
            logger.exception(msg, error=str(e), options=options, signals_type="video_export")
            raise RuntimeError(msg) from e


class PlaywrightRecorder(_ReplayVideoRecorder):
    """Record a replay to a file using Playwright."""

    def record(self) -> RecordingResult:
        """Record a replay to a file using Playwright."""
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
            if self.opts.screenshot_width is not None and self.opts.screenshot_height is not None:
                # Use provided dimensions
                width = self.opts.screenshot_width
                height = self.opts.screenshot_height
            else:
                # Phase 1: Detect actual recording resolution
                default_width = 1400  # Default fallback
                default_height = 600  # Default fallback
                width, height = self._detect_recording_resolution(
                    browser=browser,
                    url_to_render=self.opts.url_to_render,
                    wait_for_css_selector=self.opts.wait_for_css_selector,
                    default_width=default_width,
                    default_height=default_height,
                )
            # Scale dimensions if needed to fit within max width while maintaining aspect ratio
            width, height = self._scale_dimensions_if_needed(width, height)
            # Phase 2: Create recording context with exact resolution
            context = browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=self.record_dir,
                record_video_size={"width": width, "height": height},
            )
            page = context.new_page()
            record_started = time.monotonic()
            # Speed up playback for long MP4 recordings to reduce recording time
            ext = os.path.splitext(self.opts.image_path)[1].lower()
            # if playback speed is the default value for webm or mp4 then we speed it up, otherwise we respect user choice
            playback_speed = (
                PLAYBACK_SPEED_MULTIPLIER
                if (ext in [".mp4", ".webm"] and self.opts.recording_duration > 5 and self.opts.playback_speed == 1)
                else self.opts.playback_speed
            )
            # Navigate with correct dimensions
            self._wait_for_page_ready(
                page,
                self._ensure_playback_speed(self.opts.url_to_render, playback_speed),
                self.opts.wait_for_css_selector,
            )
            measured_width: Optional[int] = None
            try:
                dimensions = page.evaluate(
                    """
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
                """
                )
                final_height = dimensions["height"]
                width_candidate = dimensions["width"] or width
                measured_width = max(width, min(1800, int(width_candidate)))
                page.set_viewport_size({"width": measured_width, "height": int(final_height) + HEIGHT_OFFSET})
            except Exception as e:
                logger.exception(
                    "Failed to resize viewport to the recording resolution.",
                    error=str(e),
                    options=asdict(self.opts),
                    signals_type="video_export",
                )
                # Allow the recording to confinue even if viewport resize fails
            ready_at = time.monotonic()
            page.wait_for_timeout(500)
            # Wait for playback to reach the end while tracking segment changes
            # This allows us to record accurate video timestamps for each segment
            max_wait_ms = int((self.opts.recording_duration / playback_speed) * 1000)
            segment_start_timestamps = self._wait_for_recording_with_segments(
                page=page,
                max_wait_ms=max_wait_ms,
                playback_started=ready_at,
            )
            # Collect inactivity periods and merge with segment timestamps
            # Pass playback_speed to adjust timestamps for the final slowed-down video
            inactivity_periods = self._detect_inactivity_periods(
                page=page,
                playback_speed=playback_speed,
                segment_start_timestamps=segment_start_timestamps,
            )
            # Stop the recording, either after detecting end or reaching safety timeout
            page.close()
            video = page.video
            if video is None:
                raise RuntimeError("Playwright did not produce a video. Ensure record_video_dir is set.")
            if hasattr(video, "save_as"):
                video.save_as(self.output_path)
            else:
                src = video.path()
                if not src:
                    raise RuntimeError("Playwright did not provide a video path.")
                shutil.move(src, self.output_path)
            pre_roll = max(0.0, ready_at - record_started)
            # Clean up Playwright resources
            try:
                context.close()
                browser.close()
            except Exception:
                pass
            # Return the result
            return RecordingResult(
                video_path=self.output_path,
                pre_roll=pre_roll,
                playback_speed=playback_speed,
                measured_width=measured_width,
                inactivity_periods=inactivity_periods,
                segment_start_timestamps=segment_start_timestamps,
            )

    def _wait_for_page_ready(self, page: Page, url_to_render: str, wait_for_css_selector: str) -> None:
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

    def _scale_dimensions_if_needed(self, width: int, height: int, max_size: int = 1400) -> tuple[int, int]:
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
        return scaled_width, scaled_height

    def _detect_recording_resolution(
        self,
        browser: Browser,
        url_to_render: str,
        wait_for_css_selector: str,
        default_width: int,
        default_height: int,
    ) -> tuple[int, int]:
        # Create temporary context just for resolution detection
        context = browser.new_context(
            viewport={"width": default_width, "height": default_height},
        )
        page = context.new_page()
        try:
            # Navigate and wait for player to load
            self._wait_for_page_ready(page, url_to_render, wait_for_css_selector)

            # Wait for resolution to be available from sessionRecordingPlayerLogic global variable
            try:
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
                return detected_width, detected_height
            except Exception as e:
                logger.exception(
                    "Failed to detect recording resolution.",
                    error=str(e),
                    options=asdict(self.opts),
                    signals_type="video_export",
                )
                return default_width, default_height
        finally:
            # Clean up detection context
            page.close()
            context.close()

    def _detect_inactivity_periods(
        self,
        page: Page,
        playback_speed: int,
        segment_start_timestamps: dict[float, float] | None = None,
    ) -> list[ReplayInactivityPeriod] | None:
        """
        Detect inactivity periods when recording session videos.
        If segment_timestamps is provided, merges video timestamps into periods.
        Timestamps are adjusted for playback_speed since the final video is slowed down
        using setpts={playback_speed}*PTS to show the session at normal 1x speed.
        """
        try:
            # Get data from the global variable using browser
            inactivity_periods_raw = page.wait_for_function(
                """
                () => {
                    const r = (window).__POSTHOG_INACTIVITY_PERIODS__;
                    if (!r) return [];
                    return r.map(p => ({
                        ts_from_s: Number(p.ts_from_s),
                        ts_to_s: p.ts_to_s !== undefined ? Number(p.ts_to_s) : null,
                        active: Boolean(p.active),
                    }));
                }
                """,
                timeout=15000,
            ).json_value()

            # Merge segment timestamps into periods if provided
            # Adjust for playback_speed since video is slowed down in post-processing
            if segment_start_timestamps:
                for period in inactivity_periods_raw:
                    ts_from_s = period.get("ts_from_s")
                    if ts_from_s is not None and ts_from_s in segment_start_timestamps:
                        # Raw timestamp * playback_speed = final video timestamp
                        # (video is slowed down by playback_speed in ffmpeg)
                        raw_timestamp = segment_start_timestamps[ts_from_s]
                        period["recording_ts_from_s"] = raw_timestamp * playback_speed

            inactivity_periods = [ReplayInactivityPeriod.model_validate(period) for period in inactivity_periods_raw]
            return inactivity_periods
        except Exception as e:
            logger.exception(
                "Failed to detect inactivity periods.",
                error=str(e),
                options=asdict(self.opts),
                signals_type="video_export",
            )
            return None

    def _wait_for_recording_with_segments(
        self,
        page: Page,
        max_wait_ms: int,
        playback_started: float,
    ) -> dict[float, float]:
        """
        Wait for recording to end while tracking segment changes.
        Returns a dict mapping ts_from_s -> video_timestamp_seconds for each segment.
        """

        # Track time from the video start related to the in-player start timestamps
        segment_start_timestamps: dict[float, float] = {}
        last_counter = 0
        while True:
            # Check if the recording should be ended by now and stop it manually
            elapsed_ms = (time.monotonic() - playback_started) * 1000
            if elapsed_ms >= max_wait_ms:
                logger.exception(
                    "Recording wait timeout reached. Stopping the recording manually.",
                    elapsed_ms=elapsed_ms,
                    max_wait_ms=max_wait_ms,
                    options=asdict(self.opts),
                    signals_type="video_export",
                )
                # Stop the recording manually
                break
            try:
                # Wait for either: recording ended OR segment counter changed
                remaining_ms = max_wait_ms - elapsed_ms
                result = page.wait_for_function(
                    f"""
                    () => {{
                        if (window.__POSTHOG_RECORDING_ENDED__) return {{ ended: true }};
                        const counter = window.__POSTHOG_SEGMENT_COUNTER__ || 0;
                        if (counter > {last_counter}) return {{
                            counter: counter,
                            segment_start_ts: window.__POSTHOG_CURRENT_SEGMENT_START_TS__
                        }};
                        return null;
                    }}
                    """,
                    # The check should be instant (if present), or up to 1s
                    timeout=min(1000, remaining_ms),
                ).json_value()
                # If no globals are available
                if result is None:
                    continue
                # If the recording ended, assuming all the required data was already collected
                if result.get("ended"):
                    break
                # Segment changed - record the video timestamp on BE to be consistent (rendering delays, etc.)
                segment_start_ts = result.get("segment_start_ts")
                new_counter = result.get("counter", 0)
                if segment_start_ts is not None and new_counter > last_counter:
                    video_time = time.monotonic() - playback_started
                    segment_start_timestamps[segment_start_ts] = video_time
                    last_counter = new_counter

            # No change in 1s, continue waiting
            except PlaywrightTimeoutError:
                continue
            # Unexpected error, continue waiting
            except Exception as e:
                logger.exception(
                    "Unexpected error while waiting for recording with segments.",
                    error=str(e),
                    options=asdict(self.opts),
                    signals_type="video_export",
                )
                # Continue waiting despite errors
                continue
        return segment_start_timestamps

    def _ensure_playback_speed(self, url_to_render: str, playback_speed: int) -> str:
        """
        the export function might choose to change the playback speed
        and so needs to update the URL to let the UI know what playback speed
        to use when rendering the video.
        """
        parsed_url = urlparse(url_to_render)
        query_params = parse_qs(parsed_url.query)
        query_params["playerSpeed"] = [str(playback_speed)]
        new_query = urlencode(query_params, doseq=True)
        return str(urlunparse(parsed_url._replace(query=new_query)))


class ReplayVideoRenderer:
    def __init__(
        self,
        temp_output_path: str,
        image_path: str,
        pre_roll: float,
        recording_duration: int,
        playback_speed: int,
        measured_width: int | None = None,
        fps_to_render_at: int | None = None,
    ):
        self.temp_output_path = temp_output_path
        self.image_path = image_path
        self.pre_roll = pre_roll
        self.recording_duration = recording_duration
        self.playback_speed = playback_speed
        self.measured_width = measured_width
        self.fps_to_render_at = fps_to_render_at

    def _define_video_filter(self) -> str | None:
        vf_parts = []
        if self.playback_speed > 1.0:
            vf_parts.append(f"setpts={self.playback_speed}*PTS")
        if self.fps_to_render_at:
            vf_parts.append(f"fps={self.fps_to_render_at}")
        video_filter = ",".join(vf_parts) if vf_parts else None
        return video_filter

    def _convert_to_mp4(self) -> None:
        """Render recording in MP4 using ffmpeg."""
        video_filter = self._define_video_filter()
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{self.pre_roll:.2f}",
            "-i",
            self.temp_output_path,
            "-t",
            f"{float(self.recording_duration):.2f}",
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
        cmd.append(self.image_path)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            error_msg = f"ffmpeg failed with exit code {e.returncode}"
            if e.stderr:
                error_msg += f": {e.stderr.strip()}"
            raise RuntimeError(error_msg) from e

    def _process_webm(self) -> None:
        """Process WebM with speed correction using ffmpeg."""
        video_filter = self._define_video_filter()
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{self.pre_roll:.2f}",
            "-i",
            self.temp_output_path,
            "-t",
            f"{float(self.recording_duration):.2f}",
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "30",
            "-b:v",
            "0",
            "-f",
            "webm",
        ]
        if video_filter:
            cmd.extend(["-vf", video_filter])
        cmd.append(self.image_path)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            error_msg = f"ffmpeg failed with exit code {e.returncode}"
            if e.stderr:
                error_msg += f": {e.stderr.strip()}"
            raise RuntimeError(error_msg) from e

    def _convert_to_gif(self) -> None:
        """Convert WebM to GIF using ffmpeg."""
        # Custom filter because of GIF
        vf_parts = ["fps=12"]
        if self.measured_width is not None:
            vf_parts.append(f"scale={self.measured_width}:-2:flags=lanczos")
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
                    f"{self.pre_roll:.2f}",
                    "-t",
                    f"{float(self.recording_duration):.2f}",
                    "-i",
                    self.temp_output_path,
                    "-vf",
                    f"{vf},split[s0][s1];[s0]palettegen=stats_mode=single[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                    "-loop",
                    "0",
                    "-f",
                    "gif",
                    self.image_path,
                ],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            error_msg = f"ffmpeg failed with exit code {e.returncode}"
            if e.stderr:
                error_msg += f": {e.stderr.strip()}"
            raise RuntimeError(error_msg) from e


def record_replay_to_file(
    opts: RecordReplayToFileOptions,
) -> list[ReplayInactivityPeriod] | None:
    # Check if ffmpeg is available for video conversion
    ext = os.path.splitext(opts.image_path)[1].lower()
    if ext in [".mp4", ".gif"] and not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required for MP4 and GIF exports but was not found in PATH")
    temp_dir_ctx: Optional[tempfile.TemporaryDirectory] = None
    try:
        # Create temporary paths
        temp_dir_ctx = tempfile.TemporaryDirectory(prefix="ph-video-export-", ignore_cleanup_errors=True)
        record_dir = temp_dir_ctx.name
        temp_output_path = os.path.join(record_dir, f"{uuid.uuid4()}{ext}")
        # Choose recording method: Puppeteer or Playwright
        use_puppeteer = opts.use_puppeteer
        if use_puppeteer:
            # ============ Node.js + Puppeteer recording ============
            logger.debug("Using Node.js + Puppeteer recorder.", options=asdict(opts), signals_type="video_export")
            result = PuppeteerRecorder(
                output_path=temp_output_path,
                record_dir=record_dir,
                opts=opts,
            ).record()
            # We use 25 as multiplier when recording with Puppeteer, so it shold be slowed down to 25 FPS in the final video
            fps_to_render_at = 25
        else:
            # ============ Python + Playwright recording ============
            logger.debug("Using Python + Playwright recorder.", options=asdict(opts), signals_type="video_export")
            result = PlaywrightRecorder(
                output_path=temp_output_path,
                record_dir=record_dir,
                opts=opts,
            ).record()
            # Use default rendering logic for Playwright, as we don't modify the FPS during recording
            fps_to_render_at = None
        # ============ Common post-processing (ffmpeg) ============
        logger.debug(
            "Recording complete.",
            pre_roll=result.pre_roll,
            playback_speed=result.playback_speed,
            recording_duration=opts.recording_duration,
            segment_count=len(result.segment_start_timestamps) if result.segment_start_timestamps else 0,
            options=asdict(opts),
            signals_type="video_export",
        )
        video_renderer = ReplayVideoRenderer(
            temp_output_path=temp_output_path,
            image_path=opts.image_path,
            pre_roll=result.pre_roll,
            recording_duration=opts.recording_duration,
            playback_speed=result.playback_speed,
            measured_width=result.measured_width,
            fps_to_render_at=fps_to_render_at,
        )
        if ext == ".mp4":
            video_renderer._convert_to_mp4()
        elif ext == ".gif":
            video_renderer._convert_to_gif()
        elif ext == ".webm":
            if result.playback_speed > 1:
                video_renderer._process_webm()
            else:
                shutil.move(temp_output_path, opts.image_path)
        else:
            shutil.move(temp_output_path, opts.image_path)
        return result.inactivity_periods
    except Exception as e:
        with posthoganalytics.new_context():
            posthoganalytics.tag("url_to_render", opts.url_to_render)
            posthoganalytics.tag("video_target_path", opts.image_path)
            posthoganalytics.capture_exception(e)
        raise
    finally:
        if temp_dir_ctx:
            temp_dir_ctx.cleanup()
