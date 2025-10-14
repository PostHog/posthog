import io
import os
import uuid
from typing import Optional

from django.db import transaction

import structlog
import posthoganalytics
from celery import shared_task
from PIL import Image

from posthog.exceptions_capture import capture_exception
from posthog.models.heatmap_screenshot import HeatmapScreenshot
from posthog.tasks.exports.image_exporter import HEIGHT_OFFSET, get_driver
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

TMP_DIR = "/tmp"


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.EXPORTS.value,
    autoretry_for=(Exception,),
    retry_backoff=2,
    retry_backoff_max=60,
    max_retries=3,
)
@transaction.atomic
def generate_heatmap_screenshot(screenshot_id: int) -> None:
    """
    Generate a screenshot of a website for heatmap purposes.
    Similar to image_exporter but for arbitrary URLs.
    """
    try:
        screenshot = HeatmapScreenshot.objects.select_related("team", "created_by").get(id=screenshot_id)
    except HeatmapScreenshot.DoesNotExist:
        logger.exception("heatmap_screenshot.not_found", screenshot_id=screenshot_id)
        return

    with posthoganalytics.new_context():
        posthoganalytics.tag("team_id", screenshot.team_id)
        posthoganalytics.tag("screenshot_id", screenshot.id)

        try:
            _generate_screenshot(screenshot)

            screenshot.status = HeatmapScreenshot.Status.COMPLETED
            screenshot.save()

            logger.info(
                "heatmap_screenshot.completed",
                screenshot_id=screenshot.id,
                team_id=screenshot.team_id,
                url=screenshot.url,
            )

        except Exception as e:
            screenshot.status = HeatmapScreenshot.Status.FAILED
            screenshot.exception = str(e)
            screenshot.save()

            logger.exception(
                "heatmap_screenshot.failed",
                screenshot_id=screenshot.id,
                team_id=screenshot.team_id,
                url=screenshot.url,
                exception=str(e),
                exc_info=True,
            )

            capture_exception(
                e,
                additional_properties={
                    "celery_task": "heatmap_screenshot",
                    "team_id": screenshot.team_id,
                    "screenshot_id": screenshot.id,
                },
            )
            raise


def _generate_screenshot(screenshot: HeatmapScreenshot) -> None:
    """Generate screenshot using Selenium WebDriver."""
    image_path = None
    driver: Optional = None

    try:
        image_id = str(uuid.uuid4())
        image_path = os.path.join(TMP_DIR, f"heatmap_screenshot_{image_id}.png")

        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)

        driver = get_driver()

        # Set window size to requested width with reasonable initial height
        driver.set_window_size(screenshot.width, 800)

        # Navigate to URL
        driver.get(screenshot.url)
        posthoganalytics.tag("url", screenshot.url)

        # Wait for page to load
        driver.implicitly_wait(1000)

        # Get full page height
        total_height = driver.execute_script(
            "return Math.max(document.body.scrollHeight, document.body.offsetHeight, "
            "document.documentElement.clientHeight, document.documentElement.scrollHeight, "
            "document.documentElement.offsetHeight);"
        )

        # Set window to full page size
        driver.set_window_size(screenshot.width, total_height + HEIGHT_OFFSET)

        # Allow page to adjust to new size
        driver.execute_script("return new Promise(resolve => setTimeout(resolve, 1000))")

        # Take screenshot
        driver.save_screenshot(image_path)

        # Process and compress the image
        with Image.open(image_path) as img:
            # Scale down if width > 1400px, keeping aspect ratio
            if img.width > 1400:
                ratio = 1400 / img.width
                new_height = int(img.height * ratio)
                img = img.resize((1400, new_height), Image.Resampling.LANCZOS)

            # Convert to RGB for JPEG (remove transparency)
            if img.mode in ("RGBA", "LA", "P"):
                rgb_img = Image.new("RGB", img.size, (255, 255, 255))  # White background
                if img.mode == "P":
                    img = img.convert("RGBA")
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = rgb_img

            # Save as JPEG with 80% quality
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=80, optimize=True)
            image_data = buffer.getvalue()

        screenshot.content = image_data

        # Clean up temp file
        os.remove(image_path)

    except Exception:
        # Clean up on error
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

        if driver:
            try:
                driver.save_screenshot(image_path)
                posthoganalytics.tag("error_screenshot_path", image_path)
            except Exception:
                pass

        raise
    finally:
        if driver:
            driver.quit()
