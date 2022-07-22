import logging
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
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.utils import ChromeType

from posthog.internal_metrics import incr, timing
from posthog.logging.timing import timed
from posthog.models.exported_asset import ExportedAsset, get_public_access_token, save_content
from posthog.tasks.update_cache import synchronously_update_insight_cache
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
        service=Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM, log_level=logging.ERROR).install()),
        options=options,
    )


def _export_to_png(exported_asset: ExportedAsset) -> None:
    """
    Exporting an Insight means:
    1. Loading the Insight from the web app in a dedicated rendering mode
    2. Waiting for the page to have fully loaded before taking a screenshot to disk
    3. Loading that screenshot into memory and saving the data representation to the relevant Insight
    4. Cleanup: Remove the old file and close the browser session
    """

    _start = time.time()

    image_path = None

    try:
        if not settings.SITE_URL:
            raise Exception(
                "The SITE_URL is not set. The exporter must have HTTP access to the web app in order to work"
            )

        image_id = str(uuid.uuid4())
        image_path = os.path.join(TMP_DIR, f"{image_id}.png")

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

        _screenshot_asset(image_path, url_to_render, screenshot_width, wait_for_css_selector)

        with open(image_path, "rb") as image_file:
            image_data = image_file.read()

        save_content(exported_asset, image_data)

        os.remove(image_path)
        timing("exporter_task_success", time.time() - _start)

    except Exception as err:
        # Ensure we clean up the tmp file in case anything went wrong
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

        raise err


def _screenshot_asset(
    image_path: str, url_to_render: str, screenshot_width: ScreenWidth, wait_for_css_selector: CSSSelector,
) -> None:
    driver: Optional[webdriver.Chrome] = None
    try:
        driver = get_driver()
        driver.set_window_size(screenshot_width, screenshot_width * 0.5)
        driver.get(url_to_render)
        WebDriverWait(driver, 10).until(lambda x: x.find_element(By.CSS_SELECTOR, wait_for_css_selector))
        height = driver.execute_script("return document.body.scrollHeight")
        driver.set_window_size(screenshot_width, height)
        driver.save_screenshot(image_path)
    finally:
        if driver:
            driver.close()


@timed("image_exporter")
def export_image(exported_asset: ExportedAsset) -> None:
    try:
        if exported_asset.insight:
            # NOTE: Dashboards are regularly updated but insights are not
            # so, we need to trigger a manual update to ensure the results are good
            synchronously_update_insight_cache(exported_asset.insight, dashboard=exported_asset.dashboard)

        if exported_asset.export_format == "image/png":
            _export_to_png(exported_asset)
            statsd.incr("image_exporter.succeeded", tags={"team_id": exported_asset.team.id})
        else:
            raise NotImplementedError(f"Export to format {exported_asset.export_format} is not supported for insights")
    except Exception as e:
        if exported_asset:
            team_id = str(exported_asset.team.id)
        else:
            team_id = "unknown"

        capture_exception(e)

        logger.error("image_exporter.failed", exception=e, exc_info=True)
        incr("exporter_task_failure", tags={"team_id": team_id})
        raise e
