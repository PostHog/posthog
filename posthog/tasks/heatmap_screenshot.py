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
from posthog.models.heatmap_screenshot import HeatmapScreenshot, HeatmapSnapshot
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
def generate_heatmap_screenshot(screenshot_id: str) -> None:
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
            _generate_screenshots(screenshot)

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


def _generate_screenshots(screenshot: HeatmapScreenshot) -> None:
    """Generate screenshots for multiple widths using a single Selenium WebDriver session."""
    driver: Optional = None
    temp_files: list[str] = []

    # Determine target widths
    target_widths = screenshot.target_widths or [320, 375, 425, 768, 1024, 1440, 1920]
    # Deduplicate and keep order
    seen = set()
    widths: list[int] = []
    for w in target_widths:
        if isinstance(w, int) and 100 <= w <= 3000 and w not in seen:
            widths.append(w)
            seen.add(w)

    if not widths:
        widths = [1024]

    try:
        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)

        driver = get_driver()

        # Navigate once
        driver.set_window_size(1024, 800)
        driver.get(screenshot.url)
        posthoganalytics.tag("url", screenshot.url)
        driver.implicitly_wait(1000)

        for w in widths:
            image_id = str(uuid.uuid4())
            image_path = os.path.join(TMP_DIR, f"heatmap_screenshot_{image_id}_{w}.png")
            temp_files.append(image_path)

            # Set window to width and initial height
            driver.set_window_size(w, 800)

            # Compute full page height
            total_height = driver.execute_script(
                "return Math.max(document.body.scrollHeight, document.body.offsetHeight, "
                "document.documentElement.clientHeight, document.documentElement.scrollHeight, "
                "document.documentElement.offsetHeight);"
            )

            # Resize to full height for capture
            driver.set_window_size(w, total_height + HEIGHT_OFFSET)
            driver.execute_script("return new Promise(resolve => setTimeout(resolve, 1000))")

            # Take screenshot
            driver.save_screenshot(image_path)

            # Process and compress to JPEG (keep exact width; no downscale)
            with Image.open(image_path) as img:
                if img.mode in ("RGBA", "LA", "P"):
                    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                    img = rgb_img

                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=80, optimize=True)
                image_data = buffer.getvalue()

            # Upsert snapshot for this width
            snapshot, _ = HeatmapSnapshot.objects.get_or_create(heatmap=screenshot, width=w)
            snapshot.content = image_data
            snapshot.content_location = None
            snapshot.save()

    except Exception:
        # Attempt to capture an error screenshot path for diagnostics
        if driver:
            try:
                err_path = os.path.join(TMP_DIR, f"heatmap_error_{uuid.uuid4()}.png")
                driver.save_screenshot(err_path)
                posthoganalytics.tag("error_screenshot_path", err_path)
            except Exception:
                pass
        raise
    finally:
        # Cleanup temp files and driver
        for f in temp_files:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        if driver:
            driver.quit()
