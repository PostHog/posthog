import asyncio
import datetime
from typing import Union

from django.conf import settings

import structlog
from celery import chain
from prometheus_client import Histogram

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

SUBSCRIPTION_ASSET_GENERATION_TIMER = Histogram(
    "subscription_asset_generation_duration_seconds",
    "Time spent generating assets for a subscription",
    labelnames=["execution_path"],
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
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
    with SUBSCRIPTION_ASSET_GENERATION_TIMER.labels(execution_path="temporal").time():
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
                logger.info("generate_assets_async.exporting_asset", asset_id=asset.id)
                await database_sync_to_async(exporter.export_asset_direct, thread_sensitive=False)(asset)
                logger.info("generate_assets_async.asset_exported", asset_id=asset.id)
            except Exception as e:
                logger.error(
                    "generate_assets_async.export_failed",
                    asset_id=asset.id,
                    subscription_id=getattr(resource, "id", None),
                    error=str(e),
                    exc_info=True,
                )
                # Save the exception but continue with other assets
                asset.exception = str(e)
                await database_sync_to_async(asset.save, thread_sensitive=False)()

        # Run all exports concurrently
        logger.info("generate_assets_async.starting_exports", asset_count=len(assets))
        await asyncio.gather(*[export_single_asset(asset) for asset in assets])
        logger.info("generate_assets_async.exports_complete", asset_count=len(assets))

        return insights, assets
