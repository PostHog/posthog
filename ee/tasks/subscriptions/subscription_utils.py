import datetime
from typing import TYPE_CHECKING, Union

from django.conf import settings

import structlog
from celery import chain
from prometheus_client import Histogram

from posthog.constants import AvailableFeature
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.tasks import exporter
from posthog.utils import wait_for_parallel_celery_group

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription
from products.product_analytics.backend.models.insight import Insight

if TYPE_CHECKING:
    from posthog.models.organization import Organization

logger = structlog.get_logger(__name__)

UTM_TAGS_BASE = "utm_source=posthog&utm_campaign=subscription_report"
# Per-subscription insight caps. The live cap comes from the `subscription_insights` billing
# entitlement; these are the fallbacks used until billing emits it (see
# get_max_asset_count_for_organization). Keep in sync with FREE_TIER_MAX_INSIGHTS and
# PAID_TIER_MAX_INSIGHTS in frontend/src/lib/components/Subscriptions/insightSelectorLogic.ts
DEFAULT_MAX_ASSET_COUNT = 25
FREE_TIER_MAX_ASSET_COUNT = 6
ASSET_GENERATION_FAILED_MESSAGE = "Failed to generate content"
# Prometheus metrics for Temporal workers (web/worker pods). Buckets run well past the 600s the
# old cap implied — a full paid dashboard renders sequentially and routinely lands in the minutes.
SUBSCRIPTION_ASSET_GENERATION_TIMER = Histogram(
    "subscription_asset_generation_duration_seconds",
    "Time spent generating assets for a subscription",
    labelnames=["execution_path"],
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, 900, 1200, 1800, float("inf")),
)


def get_max_asset_count_for_organization(organization: "Organization") -> int:
    """Resolve the per-subscription insight cap for an organization from billing.

    The cap is driven by the ``subscription_insights`` billing entitlement: orgs get the
    ``limit`` their plan grants (an absent ``limit`` on a present entitlement means unlimited,
    bounded to DEFAULT_MAX_ASSET_COUNT for operational safety). Until billing emits the
    entitlement, fall back to the plan tier so paid orgs aren't regressed to the free cap.
    """
    feature = organization.get_available_feature(AvailableFeature.SUBSCRIPTION_INSIGHTS)
    if feature is not None:
        limit = feature.get("limit")
        return limit if limit is not None else DEFAULT_MAX_ASSET_COUNT

    return FREE_TIER_MAX_ASSET_COUNT if organization.get_plan_tier() == "free" else DEFAULT_MAX_ASSET_COUNT


def _has_asset_failed(asset: ExportedAsset) -> bool:
    # Prefer the `_db_content_present` annotation when a caller deferred the heavy `content`
    # BYTEA (delivery does, to avoid materialising every asset's bytes); fall back to reading
    # `content` directly when it wasn't deferred.
    content_present = getattr(asset, "_db_content_present", None)
    if content_present is None:
        content_present = asset.content is not None
    has_content = bool(content_present) or bool(asset.content_location)
    return not has_content or asset.exception is not None


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

        # Gate the cap on the org's billing plan, honoring any lower caller-supplied limit.
        max_asset_count = min(max_asset_count, get_max_asset_count_for_organization(resource.team.organization))

        # Create all the assets we need
        expiry = ExportedAsset.compute_expires_after(ExportedAsset.ExportFormat.PNG)
        # Attribute the asset to the subscription owner so background renders resolve warehouse
        # HogQL access control against their access (SharingConfiguration has no owner -> None).
        asset_created_by = resource.created_by if isinstance(resource, Subscription) else None
        assets = [
            ExportedAsset(
                team=resource.team,
                export_format=ExportedAsset.ExportFormat.PNG,
                insight=insight,
                dashboard=resource.dashboard,
                expires_after=expiry,
                created_by=asset_created_by,
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
