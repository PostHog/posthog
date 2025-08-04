import datetime
from typing import Union
from django.conf import settings
import structlog
from celery import chain
from prometheus_client import Histogram

from posthog.models.dashboard_tile import get_tiles_ordered_by_position
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.subscription import Subscription
from posthog.tasks import exporter
from posthog.utils import wait_for_parallel_celery_group

logger = structlog.get_logger(__name__)

UTM_TAGS_BASE = "utm_source=posthog&utm_campaign=subscription_report"
DEFAULT_MAX_ASSET_COUNT = 6

SUBSCRIPTION_ASSET_GENERATION_TIMER = Histogram(
    "subscription_asset_generation_duration_seconds",
    "Time spent generating assets for a subscription",
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)


def generate_assets(
    resource: Union[Subscription, SharingConfiguration],
    max_asset_count: int = DEFAULT_MAX_ASSET_COUNT,
) -> tuple[list[Insight], list[ExportedAsset]]:
    with SUBSCRIPTION_ASSET_GENERATION_TIMER.time():
        if resource.dashboard:
            tiles = get_tiles_ordered_by_position(resource.dashboard, "sm")
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

        # Wait for all assets to be exported
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
