from django.db import transaction

import structlog
import posthoganalytics
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.models.heatmap_screenshot import HeatmapScreenshot, HeatmapSnapshot
from posthog.tasks.exports.image_exporter import HEIGHT_OFFSET
from posthog.tasks.utils import CeleryQueue

from playwright.sync_api import sync_playwright

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
    """Generate screenshots for multiple widths using Playwright in one browser session."""

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

    # Collect screenshots in-memory first to avoid Django ORM calls inside Playwright's async context
    snapshot_bytes: list[tuple[int, bytes]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--force-device-scale-factor=1",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                ],
            )
            try:
                for w in widths:
                    ctx = browser.new_context(
                        viewport={"width": int(w), "height": 800},
                        device_scale_factor=1,  # keep 1:1 CSS px -> bitmap px
                        is_mobile=(w < 500),  # trigger mobile layout on small widths
                        has_touch=(w < 500),  # some sites key on touch capability
                        user_agent=(
                            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
                            "AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/115.0.0.0 "
                            "Mobile/15E148 Safari/604.1"
                            if w < 500
                            else None
                        ),
                    )
                    page = ctx.new_page()
                    page.goto(screenshot.url, wait_until="load", timeout=120_000)

                    total_height = page.evaluate("""() => Math.max(
                        document.body.scrollHeight,
                        document.body.offsetHeight,
                        document.documentElement.clientHeight,
                        document.documentElement.scrollHeight,
                        document.documentElement.offsetHeight
                    )""")

                    page.set_viewport_size({"width": int(w), "height": int(total_height + HEIGHT_OFFSET)})
                    page.wait_for_timeout(1000)

                    image_data: bytes = page.screenshot(full_page=True, type="jpeg", quality=70)
                    snapshot_bytes.append((w, image_data))

                    ctx.close()
            finally:
                browser.close()
    except Exception:
        raise

    # Persist captured images with ORM after Playwright context (back in pure sync context)
    for w, image_data in snapshot_bytes:
        snapshot, _ = HeatmapSnapshot.objects.get_or_create(heatmap=screenshot, width=w)
        snapshot.content = image_data
        snapshot.content_location = None
        snapshot.save()
