import os
import tempfile
import time
import uuid
from datetime import timedelta
from typing import Literal, Optional

from posthog.schema_migrations.upgrade_manager import upgrade_query
import structlog
import posthoganalytics
from django.conf import settings
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

from posthog.api.services.query import process_query_dict
from posthog.exceptions_capture import capture_exception
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.exported_asset import (
    ExportedAsset,
    get_public_access_token,
    save_content,
)
from posthog.tasks.exporter import (
    EXPORT_FAILED_COUNTER,
)
from posthog.tasks.exports.exporter_utils import log_error_if_site_url_not_reachable
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)

TMP_DIR = "/tmp"  # NOTE: Externalise this to ENV var

ScreenWidth = Literal[800, 1920, 1400]
CSSSelector = Literal[".InsightCard", ".ExportedInsight", ".replayer-wrapper"]


# NOTE: We purposefully DON'T re-use the driver. It would be slightly faster but would keep an in-memory browser
# window permanently around which is unnecessary
def get_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")  # Hint: Try removing this line when debugging
    options.add_argument("--force-device-scale-factor=2")  # Scale factor for higher res image
    options.add_argument("--use-gl=swiftshader")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")  # This flag can make things slower but more reliable
    options.add_experimental_option(
        "excludeSwitches", ["enable-automation"]
    )  # Removes the "Chrome is being controlled by automated test software" bar

    # Create a unique prefix for the temporary directory
    pid = os.getpid()
    timestamp = int(time.time() * 1000)
    unique_prefix = f"chrome-profile-{pid}-{timestamp}-{uuid.uuid4()}"

    # Use TemporaryDirectory which will automatically clean up when the context manager exits
    temp_dir = tempfile.TemporaryDirectory(prefix=unique_prefix)
    options.add_argument(f"--user-data-dir={temp_dir.name}")

    # Store original HOME to restore later
    original_home = os.environ.get("HOME")

    # Necessary to let the nobody user run chromium
    os.environ["HOME"] = temp_dir.name

    try:
        if os.environ.get("CHROMEDRIVER_BIN"):
            service = webdriver.ChromeService(executable_path=os.environ["CHROMEDRIVER_BIN"])
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager(chrome_type=ChromeType.GOOGLE).install()),
                options=options,
            )

        # Restore original HOME after Chrome is created
        if original_home:
            os.environ["HOME"] = original_home
        else:
            os.environ.pop("HOME", None)

        return driver
    except Exception:
        # Restore HOME on failure too
        if original_home:
            os.environ["HOME"] = original_home
        else:
            os.environ.pop("HOME", None)
        raise


def _export_to_png(exported_asset: ExportedAsset) -> None:
    """
    Exporting an Insight means:
    1. Loading the Insight from the web app in a dedicated rendering mode
    2. Waiting for the page to have fully loaded before taking a screenshot to disk
    3. Loading that screenshot into memory and saving the data representation to the relevant Insight
    4. Cleanup: Remove the old file and close the browser session
    """

    image_path = None

    try:
        if not settings.SITE_URL:
            raise Exception(
                "The SITE_URL is not set. The exporter must have HTTP access to the web app in order to work"
            )

        image_id = str(uuid.uuid4())
        ext = (
            "mp4"
            if exported_asset.export_format == "video/mp4"
            else "webm"
            if exported_asset.export_format == "video/webm"
            else "gif"
            if exported_asset.export_format == "image/gif"
            else "png"
        )
        image_path = os.path.join(TMP_DIR, f"{image_id}.{ext}")

        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)

        access_token = get_public_access_token(exported_asset, timedelta(minutes=15))

        screenshot_width: ScreenWidth
        wait_for_css_selector: CSSSelector
        screenshot_height: int = 600
        if exported_asset.insight is not None:
            url_to_render = absolute_uri(f"/exporter?token={access_token}&legend")
            wait_for_css_selector = ".ExportedInsight"
            screenshot_width = 800
        elif exported_asset.dashboard is not None:
            url_to_render = absolute_uri(f"/exporter?token={access_token}")
            wait_for_css_selector = ".InsightCard"
            screenshot_width = 1920
        elif exported_asset.export_context and exported_asset.export_context.get("replay_id"):
            # Handle replay export using /exporter route (same as insights/dashboards)
            url_to_render = absolute_uri(
                f"/exporter?token={access_token}&t={exported_asset.export_context.get('timestamp') or 0}&fullscreen=true"
            )
            wait_for_css_selector = exported_asset.export_context.get("css_selector", ".replayer-wrapper")
            screenshot_width = exported_asset.export_context.get("width", 1400)
            screenshot_height = exported_asset.export_context.get("height", 600)

            logger.info(
                "exporting_replay",
                replay_id=exported_asset.export_context.get("replay_id"),
                timestamp=exported_asset.export_context.get("timestamp"),
                url_to_render=url_to_render,
                css_selector=wait_for_css_selector,
                token_preview=access_token[:10],
            )
        else:
            raise Exception(f"Export is missing required dashboard, insight ID, or replay_id in export_context")

        logger.info("exporting_asset", asset_id=exported_asset.id, render_url=url_to_render)

        if exported_asset.export_format == "image/png":
            _screenshot_asset(image_path, url_to_render, screenshot_width, wait_for_css_selector, screenshot_height)
        elif exported_asset.export_format in ("video/webm", "video/mp4", "image/gif"):
            _record_asset(image_path, url_to_render, screenshot_width, wait_for_css_selector, screenshot_height)
        else:
            raise Exception(f"Export to format {exported_asset.export_format} is not supported for insights")

        with open(image_path, "rb") as image_file:
            image_data = image_file.read()

        save_content(exported_asset, image_data)

        os.remove(image_path)

    except Exception:
        # Ensure we clean up the tmp file in case anything went wrong
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

        log_error_if_site_url_not_reachable()

        raise


# Newer versions of selenium seem to include the search bar in the height calculation.
# This is a manually determined offset to ensure the screenshot is the correct height.
# See https://github.com/SeleniumHQ/selenium/issues/14660.
HEIGHT_OFFSET = 85


def _screenshot_asset(
    image_path: str,
    url_to_render: str,
    screenshot_width: ScreenWidth,
    wait_for_css_selector: CSSSelector,
    screenshot_height: int = 600,
) -> None:
    driver: Optional[webdriver.Chrome] = None
    try:
        driver = get_driver()
        # Set initial window size with a more reasonable height to prevent initial rendering issues
        driver.set_window_size(screenshot_width, screenshot_height)
        driver.get(url_to_render)
        WebDriverWait(driver, 20).until(lambda x: x.find_element(By.CSS_SELECTOR, wait_for_css_selector))
        # Also wait until nothing is loading
        try:
            WebDriverWait(driver, 20).until_not(lambda x: x.find_element(By.CLASS_NAME, "Spinner"))
        except TimeoutException:
            logger.exception(
                "image_exporter.timeout",
                url_to_render=url_to_render,
                wait_for_css_selector=wait_for_css_selector,
                image_path=image_path,
            )
            with posthoganalytics.new_context():
                posthoganalytics.tag("url_to_render", url_to_render)
                try:
                    driver.save_screenshot(image_path)
                    posthoganalytics.tag("image_path", image_path)
                except Exception:
                    pass
                capture_exception()

        # Get the height of the visualization container specifically
        height = driver.execute_script(
            """
            const element = document.querySelector('.InsightCard__viz') ||
                          document.querySelector('.ExportedInsight__content') ||
                          document.querySelector('.replayer-wrapper');
            if (element) {
                const rect = element.getBoundingClientRect();
                return Math.max(rect.height, document.body.scrollHeight);
            }
            return document.body.scrollHeight;
        """
        )

        # For example funnels use a table that can get very wide, so try to get its width
        # For replay players, check for player width
        width = driver.execute_script(
            """
            // Check for replay player first
            const replayElement = document.querySelector('.replayer-wrapper');
            if (replayElement) {
                return replayElement.offsetWidth;
            }
            // Fall back to table width for insights
            const tableElement = document.querySelector('table');
            if (tableElement) {
                return tableElement.offsetWidth * 1.5;
            }
        """
        )
        if isinstance(width, int):
            width = max(int(screenshot_width), min(1800, width or screenshot_width))
        else:
            width = screenshot_width

        # Set window size with the calculated dimensions
        driver.set_window_size(width, height + HEIGHT_OFFSET)

        # Allow a moment for any dynamic resizing
        driver.execute_script("return new Promise(resolve => setTimeout(resolve, 500))")

        # Get the final height after any dynamic adjustments
        final_height = driver.execute_script(
            """
            const element = document.querySelector('.InsightCard__viz') ||
                          document.querySelector('.ExportedInsight__content') ||
                          document.querySelector('.replayer-wrapper');
            if (element) {
                const rect = element.getBoundingClientRect();
                return Math.max(rect.height, document.body.scrollHeight);
            }
            return document.body.scrollHeight;
        """
        )

        # Set final window size
        driver.set_window_size(width, final_height + HEIGHT_OFFSET)
        driver.save_screenshot(image_path)
    except Exception as e:
        # To help with debugging, add a screenshot and any chrome logs
        with posthoganalytics.new_context():
            posthoganalytics.tag("url_to_render", url_to_render)
            if driver:
                # If we encounter issues getting extra info we should silently fail rather than creating a new exception
                try:
                    driver.save_screenshot(image_path)
                    posthoganalytics.tag("image_path", image_path)
                except Exception:
                    pass
        capture_exception(e)

        raise
    finally:
        if driver:
            driver.quit()


def _record_asset(
    image_path: str,  # for video too; pass a .webm path
    url_to_render: str,
    screenshot_width: ScreenWidth,
    wait_for_css_selector: CSSSelector,
    screenshot_height: int = 600,
) -> None:
    """
    Record a 5-second WebM video of the exported asset using Playwright (Chromium).
    - Opens a headless browser
    - Loads the replay URL
    - Waits for content and spinner to settle
    - Records 5 seconds
    - Saves the video to `image_path` (.webm)
    """
    # Lazy import so normal image exports don't require playwright
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except Exception as import_err:
        # Give a clear actionable message
        raise RuntimeError(
            "Playwright is required for video export. Install it and Chromium, e.g.: "
            "`uv add playwright && python -m playwright install chromium`"
        ) from import_err

    temp_dir_ctx: Optional[tempfile.TemporaryDirectory] = None
    try:
        temp_dir_ctx = tempfile.TemporaryDirectory(prefix="ph-video-export-")
        record_dir = temp_dir_ctx.name

        # Clear Chrome temp HOME that might be deleted
        original_home = os.environ.get("HOME")
        if original_home and "chrome-profile" in original_home:
            # Reset to user's actual home or remove entirely
            os.environ["HOME"] = os.path.expanduser("~")

        with sync_playwright() as p:
            headless = os.getenv("EXPORTER_HEADLESS", "1") != "0"
            browser = p.chromium.launch(
                headless=headless,
                devtools=not headless,
                args=[
                    "--no-sandbox",
                    # "--disable-gpu",#TMP
                    "--disable-dev-shm-usage",
                    "--use-gl=swiftshader",
                    "--disable-software-rasterizer",
                    "--force-device-scale-factor=2",
                ],
            )

            # Start with a reasonable viewport; Playwright video size must be fixed at context creation.
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
                # Still try to proceed, mirroring Selenium's tolerant behavior
                logger.exception("video_exporter.goto_timeout", url_to_render=url_to_render)

            # Wait for the main element to exist
            try:
                page.wait_for_selector(wait_for_css_selector, state="visible", timeout=20000)
            except PlaywrightTimeoutError:
                logger.exception(
                    "video_exporter.wait_for_selector_timeout",
                    url_to_render=url_to_render,
                    wait_for_css_selector=wait_for_css_selector,
                )

            # Try to wait for spinner to be gone
            try:
                page.wait_for_selector(".Spinner", state="detached", timeout=20000)
            except PlaywrightTimeoutError:
                logger.info("video_exporter.spinner_still_visible", url_to_render=url_to_render)

            # Best-effort: compute a larger content size to avoid cropping, but video size is fixed for the session.
            try:
                # Height detection similar to Selenium path
                final_height = page.evaluate(
                    """
                    () => {
                        const el = document.querySelector('.replayer-wrapper');
                        if (el) {
                            const rect = el.getBoundingClientRect();
                            return Math.max(rect.height, document.body.scrollHeight);
                        }
                        return document.body.scrollHeight;
                    }
                    """
                )
                # Width detection for tables / replay player
                final_width = (
                    page.evaluate(
                        """
                    () => {
                        const replay = document.querySelector('.replayer-wrapper');
                        if (replay) { return replay.offsetWidth || 0; }
                        const table = document.querySelector('table');
                        if (table) { return Math.floor((table.offsetWidth || 0) * 1.5); }
                        return 0;
                    }
                    """
                    )
                    or width
                )

                # Clamp width to something reasonable
                final_width = max(width, min(1800, int(final_width)))

                # We cannot change record_video_size after the context is created, but we can adjust viewport to avoid letterboxing/cropping.
                page.set_viewport_size({"width": final_width, "height": int(final_height) + HEIGHT_OFFSET})
            except Exception:
                # Non-fatal
                logger.info("video_exporter.size_calc_failed", url_to_render=url_to_render)

            ready_at = time.monotonic()

            # Small delay so layout stabilizes
            page.wait_for_timeout(500)

            # Record 5 seconds
            page.wait_for_timeout(5000)

            # Finalize and save BEFORE closing context/browser
            video = page.video
            page.close()

            pre_roll = max(0.0, ready_at - record_started)

            import shutil
            import subprocess

            if not shutil.which("ffmpeg"):
                raise RuntimeError("ffmpeg is required for video/mp4 export. Install with `brew install ffmpeg`.")

            tmp_webm = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.webm")

            # persist to tmp webm
            if hasattr(video, "save_as"):
                video.save_as(tmp_webm)
            else:
                src = video.path()
                if not src:
                    raise RuntimeError("Playwright did not provide a video path.")
                shutil.move(src, tmp_webm)

            def to_mp4(src, dst, start=0.0, duration=5.0):
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-ss",
                        f"{start:.2f}",
                        "-i",
                        src,
                        "-t",
                        f"{duration:.2f}",
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
                        "mp4",  # add this
                        dst,
                    ],
                    check=True,
                )

            def to_gif(src, dst, start=0.0, duration=5.0, fps=12, scale_width=None):
                vf_parts = [f"fps={fps}"]
                if scale_width:
                    vf_parts.append(f"scale={scale_width}:-2:flags=lanczos")
                vf = ",".join(vf_parts)
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-ss",
                        f"{start:.2f}",
                        "-t",
                        f"{duration:.2f}",
                        "-i",
                        src,
                        "-vf",
                        f"{vf},split[s0][s1];[s0]palettegen=stats_mode=single[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                        "-loop",
                        "0",
                        "-f",
                        "gif",
                        dst,
                    ],
                    check=True,
                )

            try:
                ext = os.path.splitext(image_path)[1].lower()
                if ext == ".mp4":
                    to_mp4(tmp_webm, image_path, start=pre_roll, duration=5.0)
                elif ext == ".gif":
                    to_gif(
                        tmp_webm, image_path, start=pre_roll, duration=5.0, fps=12, scale_width=int(screenshot_width)
                    )
                else:
                    shutil.move(tmp_webm, image_path)
            finally:
                try:
                    # os.remove(tmp_webm)
                    context.close()
                    browser.close()
                except Exception as save_err:
                    with posthoganalytics.new_context():
                        posthoganalytics.tag("url_to_render", url_to_render)
                        posthoganalytics.tag("video_target_path", image_path)
                        capture_exception(save_err)
                    raise

    except Exception as e:
        with posthoganalytics.new_context():
            posthoganalytics.tag("url_to_render", url_to_render)
            posthoganalytics.tag("video_target_path", image_path)
            capture_exception(e)
        logger.error("video_exporter.failed", exception=e, exc_info=True)
        raise
    finally:
        if temp_dir_ctx:
            try:
                temp_dir_ctx.cleanup()
            except Exception:
                pass


def export_image(exported_asset: ExportedAsset) -> None:
    with posthoganalytics.new_context():
        posthoganalytics.tag("team_id", exported_asset.team.pk if exported_asset else "unknown")
        posthoganalytics.tag("asset_id", exported_asset.id if exported_asset else "unknown")

        try:
            if exported_asset.insight:
                # NOTE: Dashboards are regularly updated but insights are not
                # so, we need to trigger a manual update to ensure the results are good
                with upgrade_query(exported_asset.insight):
                    process_query_dict(
                        exported_asset.team,
                        exported_asset.insight.query,
                        dashboard_filters_json=exported_asset.dashboard.filters if exported_asset.dashboard else None,
                        limit_context=LimitContext.QUERY_ASYNC,
                        execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                        insight_id=exported_asset.insight.id,
                        dashboard_id=exported_asset.dashboard.id if exported_asset.dashboard else None,
                    )
            _export_to_png(exported_asset)
        except Exception as e:
            team_id = str(exported_asset.team.id) if exported_asset else "unknown"
            capture_exception(e, additional_properties={"celery_task": "image_export", "team_id": team_id})

            logger.error("image_exporter.failed", exception=e, exc_info=True)
            EXPORT_FAILED_COUNTER.labels(type="image").inc()
            raise
