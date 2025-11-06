import time
import asyncio
import datetime
from typing import Union

from django.conf import settings

import structlog
from celery import chain
from prometheus_client import Histogram
from temporalio import activity, workflow
from temporalio.common import MetricCounter, MetricHistogramTimedelta, MetricMeter

from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.subscription import Subscription
from posthog.sync import database_sync_to_async
from posthog.tasks import exporter
from posthog.utils import wait_for_parallel_celery_group

logger = structlog.get_logger(__name__)

UTM_TAGS_BASE = "utm_source=posthog&utm_campaign=subscription_report"
DEFAULT_MAX_ASSET_COUNT = 6
# Maximum height for screenshots in pixels. This prevents Chrome from consuming excessive memory
# when rendering very tall pages (e.g., tables with thousands of rows).
MAX_SCREENSHOT_HEIGHT_PIXELS = 5000


def _get_failed_asset_info(assets: list[ExportedAsset], resource: Union[Subscription, SharingConfiguration]) -> dict:
    failed_assets = [a for a in assets if not a.content and not a.content_location]
    failed_insight_ids = [a.insight_id for a in failed_assets if a.insight_id]
    failed_insight_urls = [
        f"/project/{resource.team_id}/insights/{a.insight.short_id}"
        for a in failed_assets
        if a.insight and hasattr(a.insight, "short_id")
    ]

    dashboard_url = f"/project/{resource.team_id}/dashboard/{resource.dashboard_id}" if resource.dashboard else None

    return {
        "failed_asset_count": len(failed_assets),
        "failed_insight_ids": failed_insight_ids,
        "failed_insight_urls": failed_insight_urls,
        "dashboard_url": dashboard_url,
    }


# Prometheus metrics for Celery workers (web/worker pods)
SUBSCRIPTION_ASSET_GENERATION_TIMER = Histogram(
    "subscription_asset_generation_duration_seconds",
    "Time spent generating assets for a subscription",
    labelnames=["execution_path"],
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)


# Temporal metrics for temporal workers
def get_metric_meter() -> MetricMeter:
    if activity.in_activity():
        return activity.metric_meter()
    elif workflow.in_workflow():
        return workflow.metric_meter()
    else:
        raise RuntimeError("Not within workflow or activity context")


def get_asset_generation_duration_metric(execution_path: str) -> MetricHistogramTimedelta:
    return (
        get_metric_meter()
        .with_additional_attributes({"execution_path": execution_path})
        .create_histogram_timedelta(
            "subscription_asset_generation_duration",
            "Time spent generating assets for a subscription",
        )
    )


def get_asset_generation_timeout_metric(execution_path: str) -> MetricCounter:
    return (
        get_metric_meter()
        .with_additional_attributes({"execution_path": execution_path})
        .create_counter(
            "subscription_asset_generation_timeout",
            "Number of times asset generation timed out during subscription delivery",
        )
    )


def generate_assets(
    resource: Union[Subscription, SharingConfiguration],
    max_asset_count: int = DEFAULT_MAX_ASSET_COUNT,
) -> tuple[list[Insight], list[ExportedAsset]]:
    with SUBSCRIPTION_ASSET_GENERATION_TIMER.labels(execution_path="celery").time():
        if resource.dashboard:
            tiles = list(
                resource.dashboard.tiles.select_related("insight")
                .filter(insight__isnull=False, insight__deleted=False)
                .all()
            )
            tiles.sort(key=lambda x: (x.layouts.get("sm", {}).get("y", 100), x.layouts.get("sm", {}).get("x", 100)))
            insights = [tile.insight for tile in tiles if tile.insight]
        elif resource.insight:
            insights = [resource.insight]
        else:
            raise Exception("There are no insights to be sent for this Subscription")

        # Create all the assets we need
        assets = [
            ExportedAsset(
                team=resource.team,
                export_format="image/png",
                insight=insight,
                dashboard=resource.dashboard,
            )
            for insight in insights[:max_asset_count]
        ]
        ExportedAsset.objects.bulk_create(assets)

        if not assets:
            return insights, assets

        tasks = [exporter.export_asset.si(asset.id) for asset in assets]
        # run them one after the other, so we don't exhaust celery workers
        exports_expire = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(
            minutes=settings.PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES
        )
        parallel_job = chain(*tasks).apply_async(expires=exports_expire, retry=False)

        wait_for_parallel_celery_group(
            parallel_job,
            expires=exports_expire,
        )

        return insights, assets


async def generate_assets_async(
    resource: Union[Subscription, SharingConfiguration],
    max_asset_count: int = DEFAULT_MAX_ASSET_COUNT,
) -> tuple[list[Insight], list[ExportedAsset]]:
    """
    Async version of generate_assets that creates assets with bulk_create then exports them concurrently.
    This function requires "created_by", "insight", "dashboard", "team" be prefetched on the resource
    """
    logger.info("generate_assets_async.starting", resource_id=getattr(resource, "id", None))
    start_time = time.time()
    try:
        if resource.dashboard:
            # Fetch tiles asynchronously
            dashboard = resource.dashboard  # Capture reference for lambda
            tiles = await database_sync_to_async(
                lambda: list(
                    dashboard.tiles.select_related("insight")
                    .filter(insight__isnull=False, insight__deleted=False)
                    .all()
                ),
                thread_sensitive=False,
            )()
            tiles.sort(key=lambda x: (x.layouts.get("sm", {}).get("y", 100), x.layouts.get("sm", {}).get("x", 100)))
            insights = [tile.insight for tile in tiles if tile.insight]
        elif resource.insight:
            insights = [resource.insight]
        else:
            raise Exception("There are no insights to be sent for this Subscription")

        # Create all the assets we need
        assets = [
            ExportedAsset(
                team=resource.team,
                export_format="image/png",
                insight=insight,
                dashboard=resource.dashboard,
            )
            for insight in insights[:max_asset_count]
        ]
        await database_sync_to_async(ExportedAsset.objects.bulk_create, thread_sensitive=False)(assets)

        if not assets:
            return insights, assets

        # Create async tasks for each asset export
        async def export_single_asset(asset: ExportedAsset) -> None:
            try:
                logger.info(
                    "generate_assets_async.exporting_asset",
                    asset_id=asset.id,
                    insight_id=asset.insight_id,
                    subscription_id=getattr(resource, "id", None),
                    team_id=resource.team_id,
                )
                await database_sync_to_async(exporter.export_asset_direct, thread_sensitive=False)(
                    asset, max_height_pixels=MAX_SCREENSHOT_HEIGHT_PIXELS
                )
                logger.info(
                    "generate_assets_async.asset_exported",
                    asset_id=asset.id,
                    insight_id=asset.insight_id,
                    subscription_id=getattr(resource, "id", None),
                    team_id=resource.team_id,
                )
            except Exception as e:
                logger.error(
                    "generate_assets_async.export_failed",
                    asset_id=asset.id,
                    insight_id=asset.insight_id,
                    subscription_id=getattr(resource, "id", None),
                    error=str(e),
                    exc_info=True,
                    team_id=resource.team_id,
                )
                # Save the exception but continue with other assets
                asset.exception = str(e)
                await database_sync_to_async(asset.save, thread_sensitive=False)()

        # Reserve buffer time for email/Slack delivery after exports
        buffer_seconds = 120  # 2 minutes
        export_timeout_seconds = (settings.TEMPORAL_TASK_TIMEOUT_MINUTES * 60) - buffer_seconds

        subscription_id = getattr(resource, "id", None)

        logger.info(
            "generate_assets_async.starting_exports",
            asset_count=len(assets),
            subscription_id=subscription_id,
            team_id=resource.team_id,
        )

        try:
            await asyncio.wait_for(
                asyncio.gather(*[export_single_asset(asset) for asset in assets]), timeout=export_timeout_seconds
            )
            logger.info(
                "generate_assets_async.exports_complete",
                asset_count=len(assets),
                subscription_id=subscription_id,
                team_id=resource.team_id,
            )
        except TimeoutError:
            get_asset_generation_timeout_metric("temporal").add(1)

            # Get failure info for logging
            failure_info = _get_failed_asset_info(assets, resource)

            logger.warning(
                "generate_assets_async.exports_timeout",
                asset_count=len(assets),
                subscription_id=subscription_id,
                dashboard_id=resource.dashboard_id if resource.dashboard else None,
                team_id=resource.team_id,
                **failure_info,
            )
            # Continue with partial results - some assets may not have content

        return insights, assets
    finally:
        duration = datetime.timedelta(seconds=time.time() - start_time)
        get_asset_generation_duration_metric("temporal").record(duration)
