import structlog
import posthoganalytics
from celery import shared_task
from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from posthog.exceptions_capture import capture_exception
from posthog.heatmaps.heatmaps_utils import DEFAULT_TARGET_WIDTHS
from posthog.models.heatmap_saved import HeatmapSnapshot, SavedHeatmap
from posthog.security.url_validation import is_url_allowed, should_block_url
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

TMP_DIR = "/tmp"


def _dismiss_cookie_banners(page: Page) -> None:
    # Try to click obvious accept/allow buttons (generic + Cookiebot)
    click_selectors = [
        # Generic
        'button:has-text("Accept")',
        'button:has-text("I Agree")',
        'button:has-text("I agree")',
        'button:has-text("Got it")',
        'button:has-text("OK")',
        'button[aria-label*="accept" i]',
        '[role="dialog"] button:has-text("Accept")',
        'button[id*="accept" i], button[class*="accept" i]',
        # OneTrust
        "#onetrust-accept-btn-handler",
        ".onetrust-accept-btn-handler",
        # Cookiebot specific
        "#CybotCookiebotDialogBodyButtonAccept",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    ]
    for sel in click_selectors:
        try:
            el = page.locator(sel).first
            # wait a short time for element to appear, then click
            el.wait_for(timeout=500)
            el.click(timeout=500)
            page.wait_for_timeout(250)
            break
        except Exception:
            pass

    # CSS-hide common cookie/consent containers and overlays
    # Important: Only target specific container elements (div, section, aside, etc.) to avoid hiding html/body
    # which may have cookie-related classes (e.g., <html class="supports-no-cookies">)
    css_hide = """
    div[id*="cookie" i], div[class*="cookie" i],
    div[id*="consent" i], div[class*="consent" i],
    div[id*="gdpr" i], div[class*="gdpr" i],
    div[id*="onetrust" i], div[class*="onetrust" i],
    div[id*="ot-sdk" i], div[class*="ot-sdk" i],
    div[id*="sp_message" i], div[class*="sp_message" i],
    div[id*="sp-consent" i], div[class*="sp-consent" i],
    div[id*="quantcast" i], div[class*="quantcast" i],
    section[id*="cookie" i], section[class*="cookie" i],
    section[id*="consent" i], section[class*="consent" i],
    section[id*="gdpr" i], section[class*="gdpr" i],
    section[id*="onetrust" i], section[class*="onetrust" i],
    section[id*="ot-sdk" i], section[class*="ot-sdk" i],
    section[id*="sp_message" i], section[class*="sp_message" i],
    section[id*="sp-consent" i], section[class*="sp-consent" i],
    section[id*="quantcast" i], section[class*="quantcast" i],
    aside[id*="cookie" i], aside[class*="cookie" i],
    aside[id*="consent" i], aside[class*="consent" i],
    aside[id*="gdpr" i], aside[class*="gdpr" i],
    aside[id*="onetrust" i], aside[class*="onetrust" i],
    aside[id*="ot-sdk" i], aside[class*="ot-sdk" i],
    aside[id*="sp_message" i], aside[class*="sp_message" i],
    aside[id*="sp-consent" i], aside[class*="sp-consent" i],
    aside[id*="quantcast" i], aside[class*="quantcast" i],
    iframe[src*="consent" i], iframe[src*="cookie" i], iframe[src*="onetrust" i],
    /* generic fixed overlays */
    div[style*="position:fixed" i][style*="z-index" i] {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
    }
    """
    try:
        page.add_style_tag(content=css_hide)
    except Exception:
        pass

    # Explicitly remove Cookiebot dialog + underlay if present (add here more specific selectors if needed)
    try:
        page.evaluate(
            """
            () => {
              document.getElementById('CybotCookiebotDialog')?.remove();
              document.getElementById('CybotCookiebotDialogBodyUnderlay')?.remove();
            }
            """
        )
    except Exception:
        pass


def _block_internal_requests(page: Page) -> None:
    page.route("**/*", lambda route: route.abort() if should_block_url(route.request.url) else route.continue_())


def _scroll_page(page: Page) -> None:
    """
    Scroll to bottom and back to top to trigger lazy-loaded content and CSS.

    Some sites lazy-load CSS, images, or other content as you scroll.
    Scrolling through the page ensures everything is loaded before screenshot.
    Uses smooth, human-like scrolling to avoid triggering scroll-based hiding.
    """
    try:
        page.evaluate(
            """
            async () => {
                // Smooth scroll function (more human-like)
                const smoothScroll = (target) => {
                    return new Promise(resolve => {
                        window.scrollTo({
                            top: target,
                            behavior: 'smooth'
                        });
                        // Wait for smooth scroll to finish
                        setTimeout(resolve, 500);
                    });
                };

                const step = window.innerHeight * 0.7;
                let maxScroll = document.body.scrollHeight;
                const maxIterations = 5; // ~3 viewport heights max
                let iterations = 0;

                // Scroll down slowly (just enough to trigger lazy loading)
                for (let y = 0; y < maxScroll && iterations < maxIterations; y += step) {
                    await smoothScroll(y);
                    await new Promise(r => setTimeout(r, 300));
                    // Re-measure as images load and page expands
                    maxScroll = Math.max(maxScroll, document.body.scrollHeight);
                    iterations++;
                }

                // Scroll to absolute bottom
                await smoothScroll(maxScroll);
                await new Promise(r => setTimeout(r, 500));

                // Scroll back to top slowly
                await smoothScroll(0);
                await new Promise(r => setTimeout(r, 500));
            }
            """
        )
        page.wait_for_timeout(500)
    except Exception:
        pass


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.EXPORTS.value,
    autoretry_for=(Exception,),
    retry_backoff=2,
    retry_backoff_max=60,
    max_retries=3,
)
def generate_heatmap_screenshot(screenshot_id: str) -> None:
    try:
        screenshot = SavedHeatmap.objects.select_related("team", "created_by").get(id=screenshot_id)
    except SavedHeatmap.DoesNotExist:
        logger.exception("heatmap_screenshot.not_found", screenshot_id=screenshot_id)
        return

    with posthoganalytics.new_context():
        posthoganalytics.tag("team_id", screenshot.team_id)
        posthoganalytics.tag("screenshot_id", screenshot.id)

        try:
            ok, err = is_url_allowed(screenshot.url)
            if not ok:
                screenshot.status = SavedHeatmap.Status.FAILED
                screenshot.exception = f"SSRF blocked: {err}"
                screenshot.save(update_fields=["status", "exception"])
                logger.warning(
                    "heatmap_screenshot.ssrf_blocked",
                    screenshot_id=screenshot.id,
                    team_id=screenshot.team_id,
                    url=screenshot.url,
                    reason=err,
                )
                return

            _generate_screenshots(screenshot)

            screenshot.status = SavedHeatmap.Status.COMPLETED
            screenshot.save()

            logger.info(
                "heatmap_screenshot.completed",
                screenshot_id=screenshot.id,
                team_id=screenshot.team_id,
                url=screenshot.url,
            )

        except Exception as e:
            screenshot.status = SavedHeatmap.Status.FAILED
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


def _generate_screenshots(screenshot: SavedHeatmap) -> None:
    # Determine target widths
    target_widths = screenshot.target_widths or DEFAULT_TARGET_WIDTHS
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
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,  # TIP: for debugging, set to False
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
                _block_internal_requests(page)

                # Start navigation and try to wait for DOM ready, but only up to 5s
                dom_ready = True
                try:
                    page.goto(screenshot.url, wait_until="domcontentloaded", timeout=5_000)
                except PlaywrightTimeoutError:
                    dom_ready = False
                    # Navigation may still continue in the background; we just won't block on it.

                # Small settle: if DOM was ready, give JS time to render (SPAs). Otherwise, brief paint time.
                page.wait_for_timeout(3000 if dom_ready else 1000)

                # Try to clear overlays/cookie banners if present
                _dismiss_cookie_banners(page)
                page.wait_for_timeout(500)

                # Scroll to bottom and back to top to trigger lazy-loaded content
                _scroll_page(page)

                # Take full-page screenshot without resizing viewport
                # (resizing viewport causes elements with vh units to expand)
                image_data: bytes = page.screenshot(full_page=True, type="jpeg", quality=70)
                snapshot_bytes.append((w, image_data))

                ctx.close()
        finally:
            browser.close()

    # Persist captured images with ORM after Playwright context (back in pure sync context)
    for w, image_data in snapshot_bytes:
        snapshot, _ = HeatmapSnapshot.objects.get_or_create(heatmap=screenshot, width=w)
        snapshot.content = image_data
        snapshot.content_location = None
        snapshot.save()
