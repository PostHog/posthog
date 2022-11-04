import json
import os
import time
import uuid
from datetime import timedelta
from typing import Literal, Optional

import structlog
from django.conf import settings
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from sentry_sdk import capture_exception, configure_scope
from statshog.defaults.django import statsd
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.utils import ChromeType

from posthog.internal_metrics import incr, timing
from posthog.logging.timing import timed
from posthog.models.exported_asset import ExportedAsset, get_public_access_token, save_content
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)

TMP_DIR = "/tmp"  # NOTE: Externalise this to ENV var

ScreenWidth = Literal[800, 1920]
CSSSelector = Literal[".InsightCard", ".ExportedInsight"]

# NOTE: We purporsefully DONT re-use the driver. It would be slightly faster but would keep an in-memory browser
# window permanently around which is unnecessary
def get_driver() -> webdriver.Chrome:
    options = Options()
    options.headless = True
    options.add_argument("--force-device-scale-factor=2")  # Scale factor for higher res image
    options.add_argument("--use-gl=swiftshader")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")  # This flag can make things slower but more reliable

    if os.environ.get("CHROMEDRIVER_BIN"):
        return webdriver.Chrome(os.environ["CHROMEDRIVER_BIN"], options=options)

    return webdriver.Chrome(
        service=Service(ChromeDriverManager(chrome_type=ChromeType.GOOGLE).install()),
        options=options,
    )


def _export_to_mp4(exported_asset: ExportedAsset) -> None:
    """
    Exporting an Insight means:
    1. Loading the Insight from the web app in a dedicated rendering mode
    2. Waiting for the page to have fully loaded before taking a screenshot to disk
    3. Loading that screenshot into memory and saving the data representation to the relevant Insight
    4. Cleanup: Remove the old file and close the browser session
    """

    _start = time.time()

    video_path = None

    try:
        if not settings.SITE_URL:
            raise Exception(
                "The SITE_URL is not set. The exporter must have HTTP access to the web app in order to work"
            )

        video_id = str(uuid.uuid4())
        video_path = os.path.join(TMP_DIR, f"{video_id}.png")

        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)

        access_token = get_public_access_token(exported_asset, timedelta(minutes=15))

        screenshot_width: ScreenWidth
        wait_for_css_selector: CSSSelector

        if exported_asset.insight is not None:
            url_to_render = absolute_uri(f"/exporter?token={access_token}&legend")
            wait_for_css_selector = ".ExportedInsight"
            screenshot_width = 800
        elif exported_asset.dashboard is not None:
            url_to_render = absolute_uri(f"/exporter?token={access_token}")
            wait_for_css_selector = ".InsightCard"
            screenshot_width = 1920
        else:
            raise Exception(f"Export is missing required dashboard or insight ID")

        logger.info("exporting_asset", asset_id=exported_asset.id, render_url=url_to_render)

        _screenshot_asset(video_path, url_to_render, screenshot_width, wait_for_css_selector)

        with open(video_path, "rb") as video_file:
            video_data = video_file.read()

        save_content(exported_asset, video_data)

        os.remove(video_path)
        timing("exporter_task_success", time.time() - _start)

    except Exception as err:
        # Ensure we clean up the tmp file in case anything went wrong
        if video_path and os.path.exists(video_path):
            os.remove(video_path)

        raise err


def _screenshot_asset(
    video_path: str, url_to_render: str, screenshot_width: ScreenWidth, wait_for_css_selector: CSSSelector
) -> None:
    driver: Optional[webdriver.Chrome] = None
    try:
        driver = get_driver()
        driver.set_window_size(screenshot_width, screenshot_width * 0.5)
        driver.get(url_to_render)
        WebDriverWait(driver, 30).until(lambda x: x.find_element(By.CSS_SELECTOR, wait_for_css_selector))
        height = driver.execute_script("return document.body.scrollHeight")
        driver.set_window_size(screenshot_width, height)
        driver.save_screenshot(video_path)
    except Exception as e:
        if driver:
            # To help with debugging, add a screenshot and any chrome logs
            with configure_scope() as scope:
                # If we encounter issues getting extra info we should silenty fail rather than creating a new exception
                try:
                    all_logs = [x for x in driver.get_log("browser")]
                    scope.add_attachment(json.dumps(all_logs).encode("utf-8"), "logs.txt")
                except Exception:
                    pass
                try:
                    driver.save_screenshot(video_path)
                    scope.add_attachment(None, None, video_path)
                except Exception:
                    pass
                capture_exception(e)

        raise e
    finally:
        if driver:
            driver.quit()


@timed("video_exporter")
def export_video(exported_asset: ExportedAsset) -> None:
    try:
        if exported_asset.export_format == ExportedAsset.ExportFormat.MP4:
            _export_to_mp4(exported_asset)
            statsd.incr("video_exporter.succeeded", tags={"team_id": exported_asset.team.id})
        else:
            raise NotImplementedError(
                f"Export to format {exported_asset.export_format} is not supported for recordings"
            )
    except Exception as e:
        if exported_asset:
            team_id = str(exported_asset.team.id)
        else:
            team_id = "unknown"

        capture_exception(e)

        logger.error("video_exporter.failed", exception=e, exc_info=True)
        incr("exporter_task_failure", tags={"team_id": team_id})
        raise e
