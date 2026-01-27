import os
import json
import time
import uuid
import tempfile
from datetime import timedelta
from typing import Literal, Optional
from urllib.parse import quote

from django.conf import settings

import structlog
import posthoganalytics
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

from posthog.schema import NodeKind

from posthog.api.insight_variable import map_stale_to_latest
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import InsightVariable
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.exported_asset import ExportedAsset, get_public_access_token, save_content
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.exporter import EXPORT_TIMER
from posthog.tasks.exports.exporter_utils import log_error_if_site_url_not_reachable
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)


def _build_cache_keys_param(insight_cache_keys: Optional[dict[int, str]]) -> str:
    if not insight_cache_keys:
        return ""
    return f"&cache_keys={quote(json.dumps(insight_cache_keys))}"


TMP_DIR = "/tmp"  # NOTE: Externalise this to ENV var

# Newer versions of selenium seem to include the search bar in the height calculation.
# This is a manually determined offset to ensure the screenshot is the correct height.
# See https://github.com/SeleniumHQ/selenium/issues/14660.
HEIGHT_OFFSET = 85
MAX_WIDTH_PIXELS = 4000  # Max width for wide content like funnels with many steps
CONTENT_PADDING = 80  # Padding for card borders

ScreenWidth = Literal[800, 1920, 1400, 4000]
CSSSelector = Literal[".InsightCard", ".ExportedInsight", ".replayer-wrapper", ".heatmap-exporter"]


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

    # Necessary to let the nobody user run chromium
    os.environ["HOME"] = temp_dir.name

    if os.environ.get("CHROMEDRIVER_BIN"):
        service = webdriver.ChromeService(executable_path=os.environ["CHROMEDRIVER_BIN"])
        return webdriver.Chrome(service=service, options=options)

    return webdriver.Chrome(
        service=Service(ChromeDriverManager(chrome_type=ChromeType.GOOGLE).install()),
        options=options,
    )


def _export_to_png(
    exported_asset: ExportedAsset,
    max_height_pixels: Optional[int] = None,
    insight_cache_keys: Optional[dict[int, str]] = None,
) -> None:
    """
    Exporting an Insight means:
    1. Loading the Insight from the web app in a dedicated rendering mode
    2. Waiting for the page to have fully loaded before taking a screenshot to disk
    3. Loading that screenshot into memory and saving the data representation to the relevant Insight
    4. Cleanup: Remove the old file and close the browser session

    Args:
        exported_asset: The asset to export
        max_height_pixels: Maximum height for the screenshot
        insight_cache_keys: Map of insight IDs to their cache keys, used to ensure
            the exporter fetches data from the exact cache that was warmed
    """
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
        screenshot_height: int = 600
        if exported_asset.insight is not None:
            show_legend = exported_asset.insight.show_legend
            legend_param = "&legend=true" if show_legend else ""
            cache_keys_param = _build_cache_keys_param(insight_cache_keys)
            url_to_render = absolute_uri(f"/exporter?token={access_token}{legend_param}{cache_keys_param}")
            wait_for_css_selector = ".ExportedInsight"
            query = exported_asset.insight.query or {}
            source = query.get("source", query)  # This to handle the InsightVizNode wrapper
            is_funnel = source.get("kind") == NodeKind.FUNNELS_QUERY
            # Set initial window size large enough for wide content like funnels with many steps
            # Small funnels will be constrained later.
            # The higher the number, the more RAM will be required by the Chromium driver.
            screenshot_width = 4000 if is_funnel else 800
        elif exported_asset.dashboard is not None:
            cache_keys_param = _build_cache_keys_param(insight_cache_keys)
            url_to_render = absolute_uri(f"/exporter?token={access_token}{cache_keys_param}")
            wait_for_css_selector = ".InsightCard"
            screenshot_width = 1920
        elif exported_asset.export_context and exported_asset.export_context.get("session_recording_id"):
            # Handle replay export using /exporter route (same as insights/dashboards)
            url_to_render = absolute_uri(
                f"/exporter?token={access_token}&t={exported_asset.export_context.get('timestamp') or 0}&fullscreen=true"
            )
            wait_for_css_selector = exported_asset.export_context.get("css_selector", ".replayer-wrapper")
            screenshot_width = exported_asset.export_context.get("width", 1400)
            screenshot_height = exported_asset.export_context.get("height", 600)

            logger.info(
                "exporting_replay",
                session_recording_id=exported_asset.export_context.get("session_recording_id"),
                timestamp=exported_asset.export_context.get("timestamp"),
                url_to_render=url_to_render,
                css_selector=wait_for_css_selector,
                token_preview=access_token[:10],
            )
        elif exported_asset.export_context and exported_asset.export_context.get("heatmap_url"):
            # Handle replay export using /exporter route (same as insights/dashboards)
            url_to_render = absolute_uri(
                f"/exporter?token={access_token}&pageURL={exported_asset.export_context.get('heatmap_url')}&dataURL={exported_asset.export_context.get('heatmap_data_url')}"
            )
            wait_for_css_selector = exported_asset.export_context.get("css_selector", ".heatmaps-ready")
            screenshot_width = exported_asset.export_context.get("width", 1400)
            screenshot_height = exported_asset.export_context.get("height", 600)

            logger.info(
                "exporting_heatmap",
                heatmap_url=exported_asset.export_context.get("heatmap_url"),
                url_to_render=url_to_render,
                css_selector=wait_for_css_selector,
                token_preview=access_token[:10],
            )
        else:
            raise Exception(
                f"Export is missing required dashboard, insight ID, or session_recording_id in export_context"
            )

        logger.info("exporting_asset", asset_id=exported_asset.id, render_url=url_to_render)

        _screenshot_asset(
            image_path, url_to_render, screenshot_width, wait_for_css_selector, screenshot_height, max_height_pixels
        )

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


def _screenshot_asset(
    image_path: str,
    url_to_render: str,
    screenshot_width: ScreenWidth,
    wait_for_css_selector: CSSSelector,
    screenshot_height: int = 600,
    max_height_pixels: Optional[int] = None,
) -> None:
    driver: Optional[webdriver.Chrome] = None
    try:
        driver = get_driver()
        driver.set_window_size(screenshot_width, screenshot_height)
        driver.get(url_to_render)
        posthoganalytics.tag("url_to_render", url_to_render)

        timeout = 20

        # For heatmaps, we need to wait until the heatmap is ready
        if wait_for_css_selector == ".heatmap-exporter":
            timeout = 100

        try:
            WebDriverWait(driver, timeout).until(lambda x: x.find_element(By.CSS_SELECTOR, wait_for_css_selector))
        except TimeoutException as e:
            with posthoganalytics.new_context():
                posthoganalytics.tag("stage", "image_exporter.page_load_timeout")
                try:
                    driver.save_screenshot(image_path)
                    posthoganalytics.tag("image_path", image_path)
                except Exception:
                    pass
                capture_exception(e)

            raise TimeoutException(f"Timeout while waiting for the page to load")

        try:
            # Also wait until nothing is loading
            WebDriverWait(driver, 20).until_not(lambda x: x.find_element(By.CLASS_NAME, "Spinner"))
        except TimeoutException as e:
            with posthoganalytics.new_context():
                posthoganalytics.tag("stage", "image_exporter.wait_for_spinner_timeout")
                try:
                    driver.save_screenshot(image_path)
                    posthoganalytics.tag("image_path", image_path)
                except Exception:
                    pass
                capture_exception(e)

        # Get the height of the visualization container specifically
        height = driver.execute_script(
            """
            const element = document.querySelector('.InsightCard__viz') ||
                          document.querySelector('.ExportedInsight__content') ||
                          document.querySelector('.replayer-wrapper') ||
                          document.querySelector('.heatmap-exporter');
            if (element) {
                const rect = element.getBoundingClientRect();
                return Math.max(rect.height, document.body.scrollHeight);
            }
            return document.body.scrollHeight;
        """
        )

        if max_height_pixels and height > max_height_pixels:
            logger.warning(
                "screenshot_height_capped",
                original_height=height,
                capped_height=max_height_pixels,
                url=url_to_render,
            )
            height = max_height_pixels

        # Calculate width for replay players and non-funnel tables
        # Funnels are handled separately with fit-content measurement below
        width = driver.execute_script(
            f"""
            // Check for replay player first
            const replayElement = document.querySelector('.replayer-wrapper');
            if (replayElement) {{
                return replayElement.offsetWidth;
            }}

            const funnelElement = document.querySelector('.FunnelBarVertical');
            if (funnelElement) {{
                // Force funnel to shrink to content size
                funnelElement.style.width = 'fit-content';
                funnelElement.style.maxWidth = 'fit-content';

                const table = funnelElement.querySelector('table');
                if (table) {{
                    table.style.width = 'fit-content';
                    table.style.maxWidth = 'fit-content';
                }}

                // Force a reflow
                void funnelElement.offsetWidth;

                // Now measure the actual content width
                return funnelElement.offsetWidth + {CONTENT_PADDING};
            }}

            // Fall back to table width for insights
            const tableElement = document.querySelector('table');
            if (tableElement) {{
                return tableElement.offsetWidth * 1.5;
            }}

            return null;
        """
        )
        if isinstance(width, (int, float)):
            calculated_width = width or screenshot_width
            if calculated_width > MAX_WIDTH_PIXELS:
                logger.warning(
                    "screenshot_width_capped",
                    original_width=calculated_width,
                    capped_width=MAX_WIDTH_PIXELS,
                    url=url_to_render,
                )
            width = min(MAX_WIDTH_PIXELS, int(calculated_width))
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
                          document.querySelector('.replayer-wrapper') ||
                          document.querySelector('.heatmap-exporter');
            if (element) {
                const rect = element.getBoundingClientRect();
                return Math.max(rect.height, document.body.scrollHeight);
            }
            return document.body.scrollHeight;
        """
        )

        if max_height_pixels and final_height > max_height_pixels:
            logger.warning(
                "screenshot_final_height_capped",
                original_final_height=final_height,
                capped_height=max_height_pixels,
                url=url_to_render,
            )
            final_height = max_height_pixels

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


def export_image(exported_asset: ExportedAsset, max_height_pixels: Optional[int] = None) -> None:
    with posthoganalytics.new_context():
        posthoganalytics.tag("team_id", exported_asset.team_id if exported_asset else "unknown")
        posthoganalytics.tag("asset_id", exported_asset.id if exported_asset else "unknown")

        try:
            # Track cache keys for insights so we can pass them to Chrome for guaranteed cache hits
            insight_cache_keys: dict[int, str] = {}

            if exported_asset.insight:
                logger.info(
                    "export_image.calculate_insight",
                    insight_id=exported_asset.insight.id,
                    dashboard_id=exported_asset.dashboard.id if exported_asset.dashboard else None,
                )

                # When exporting a single insight from a dashboard, apply the tile's filter overrides and dashboard variables
                dashboard_variables = None
                tile_filters_override = None
                if exported_asset.dashboard:
                    if exported_asset.dashboard.variables:
                        variables = list(InsightVariable.objects.filter(team=exported_asset.team).all())
                        dashboard_variables = map_stale_to_latest(exported_asset.dashboard.variables, variables)
                    tile = DashboardTile.objects.filter(
                        dashboard=exported_asset.dashboard,
                        insight=exported_asset.insight,
                    ).first()
                    if tile:
                        tile_filters_override = tile.filters_overrides

                with upgrade_query(exported_asset.insight):
                    result = calculate_for_query_based_insight(
                        exported_asset.insight,
                        team=exported_asset.team,
                        dashboard=exported_asset.dashboard,
                        execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                        user=None,
                        variables_override=dashboard_variables,
                        tile_filters_override=tile_filters_override,
                    )
                    if result.cache_key:
                        insight_cache_keys[exported_asset.insight.id] = result.cache_key
            elif exported_asset.dashboard:
                logger.info(
                    "export_image.calculate_dashboard_insights",
                    dashboard_id=exported_asset.dashboard.id,
                )
                dashboard_variables = None
                if exported_asset.dashboard.variables:
                    variables = list(InsightVariable.objects.filter(team=exported_asset.team).all())
                    dashboard_variables = map_stale_to_latest(exported_asset.dashboard.variables, variables)

                tiles = (
                    exported_asset.dashboard.tiles.select_related("insight")
                    .filter(insight__isnull=False, insight__deleted=False)
                    .all()
                )
                for tile in tiles:
                    insight = tile.insight
                    if not insight or not insight.query:
                        continue

                    with upgrade_query(insight):
                        result = calculate_for_query_based_insight(
                            insight,
                            team=exported_asset.team,
                            dashboard=exported_asset.dashboard,
                            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                            user=None,
                            variables_override=dashboard_variables,
                            tile_filters_override=tile.filters_overrides,
                        )
                        if result.cache_key:
                            insight_cache_keys[insight.id] = result.cache_key

            if exported_asset.export_format == "image/png":
                with EXPORT_TIMER.labels(type=exported_asset.export_format).time():
                    _export_to_png(
                        exported_asset,
                        max_height_pixels=max_height_pixels,
                        insight_cache_keys=insight_cache_keys or None,
                    )
            else:
                raise NotImplementedError(
                    f"Export to format {exported_asset.export_format} is not supported for insights"
                )
        except Exception as e:
            team_id = str(exported_asset.team.id) if exported_asset else "unknown"
            capture_exception(e, additional_properties={"task": "image_export", "team_id": team_id})
            logger.error("image_exporter.failed", exception=e, exc_info=True)
            raise
