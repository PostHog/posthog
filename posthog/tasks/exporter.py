import logging
import os
import time
import uuid

import structlog
from django.conf import settings
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.utils import ChromeType

from posthog.celery import app
from posthog.internal_metrics import incr, timing
from posthog.models.exported_asset import ExportedAsset
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)

TMP_DIR = "/tmp"  # NOTE: Externalise this to ENV var

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

    driver = None
    image_path = None

    try:
        if not settings.SITE_URL:
            raise Exception(
                "The SITE_URL is not set. The exporter must have HTTP access to the web app in order to work"
            )

        image_id = str(uuid.uuid4())
        image_path = os.path.join(TMP_DIR, f"{image_id}.png")

        url_to_render = None
        screenshot_width = 800

        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)

        if exported_asset.insight is not None:
            url_to_render = absolute_uri(f"/exporter/{exported_asset.access_token}")
            wait_for_css_selector = ".ExportedInsight"
            screenshot_width = 800

        elif exported_asset.dashboard is not None:
            url_to_render = absolute_uri(f"/exporter/{exported_asset.access_token}")
            wait_for_css_selector = ".InsightCard"
            screenshot_width = 1920
        else:
            raise Exception(f"Export is missing required dashboard or insight ID")

        logger.info(f"Exporting {exported_asset.id} from {url_to_render}")

        driver = get_driver()
        driver.set_window_size(screenshot_width, screenshot_width * 0.5)
        driver.get(url_to_render)

        WebDriverWait(driver, 10).until(lambda x: x.find_element(By.CSS_SELECTOR, wait_for_css_selector))

        height = driver.execute_script("return document.body.scrollHeight")

        driver.set_window_size(screenshot_width, height)
        driver.save_screenshot(image_path)

        with open(image_path, "rb") as image_file:
            image_data = image_file.read()

        exported_asset.content = image_data
        exported_asset.save()

        os.remove(image_path)
        timing("exporter_task_success", time.time() - _start)

    except Exception as err:
        # Ensure we clean up the tmp file in case anything went wrong
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

        incr("exporter_task_failure")
        logger.error(f"Error: {err}")
        raise err
    finally:
        if driver:
            driver.close()


@app.task()
def export_task(exported_asset_id: int) -> None:
    # TODO: For subscriptions: Do we want to ensure that the data for the relvant Insight(s) are up-to-date before exporting
    exported_asset = ExportedAsset.objects.get(pk=exported_asset_id)

    if exported_asset.export_format == "image/png":
        return _export_to_png(exported_asset)
    else:
        raise NotImplementedError(f"Export to format {exported_asset.export_format} is not supported")
