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
from posthog.tasks import exporter
from posthog.utils import wait_for_parallel_celery_group

logger = structlog.get_logger(__name__)

UTM_TAGS_BASE = "utm_source=posthog&utm_campaign=subscription_report"
# Keep in sync with MAX_INSIGHTS in frontend/src/lib/components/Subscriptions/insightSelectorLogic.ts
DEFAULT_MAX_ASSET_COUNT = 6
ASSET_GENERATION_FAILED_MESSAGE = "Failed to generate content"
# Prometheus metrics for Temporal workers (web/worker pods)
SUBSCRIPTION_ASSET_GENERATION_TIMER = Histogram(
    "subscription_asset_generation_duration_seconds",
    "Time spent generating assets for a subscription",
    labelnames=["execution_path"],
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)


def _has_asset_failed(asset: ExportedAsset) -> bool:
    return (not asset.content and not asset.content_location) or asset.exception is not None


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

            if isinstance(resource, Subscription) and resource.dashboard_export_insights.exists():
                selected_ids = set(resource.dashboard_export_insights.values_list("id", flat=True))
                insights = [i for i in insights if i.id in selected_ids]
        elif resource.insight:
            insights = [resource.insight]
        else:
            raise Exception("There are no insights to be sent for this Subscription")

        # Create all the assets we need
        expiry = ExportedAsset.compute_expires_after(ExportedAsset.ExportFormat.PNG)
        assets = [
            ExportedAsset(
                team=resource.team,
                export_format=ExportedAsset.ExportFormat.PNG,
                insight=insight,
                dashboard=resource.dashboard,
                expires_after=expiry,
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
