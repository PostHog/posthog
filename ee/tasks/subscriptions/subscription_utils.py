import datetime
from typing import Union

from django.conf import settings

import structlog
from celery import chain
from prometheus_client import Histogram

from posthog.dataclasses import frozen
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.tasks import exporter
from posthog.utils import wait_for_parallel_celery_group

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription
from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)

UTM_TAGS_BASE = "utm_source=posthog&utm_campaign=subscription_report"
# Keep in sync with MAX_INSIGHTS in products/subscriptions/frontend/components/Subscriptions/insightSelectorLogic.ts.
MAX_INSIGHTS = 10
ASSET_GENERATION_FAILED_MESSAGE = "Failed to generate content"
# Marks text every channel had to cut short. Shared so email, Slack and Teams read the same.
TRUNCATION_MARKER = "... (truncated)"
# Bounds one failed asset's error text so a run where several fail cannot push a message past the
# destination's payload limit on its own.
_MAX_ASSET_ERROR_LENGTH = 2000
# Locally rendered assets live on a localhost URL that Slack and Microsoft cannot fetch, so the
# message links a public placeholder instead of an image that would render broken. Keep this on a
# domain we control, because a third-party placeholder can be retired without warning.
DEBUG_PLACEHOLDER_IMAGE_URL = (
    "https://raw.githubusercontent.com/PostHog/posthog/master/frontend/public/icons/android-chrome-512x512.png"
)
# Prometheus metrics for Temporal workers (web/worker pods)
SUBSCRIPTION_ASSET_GENERATION_TIMER = Histogram(
    "subscription_asset_generation_duration_seconds",
    "Time spent generating assets for a subscription",
    labelnames=["execution_path"],
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)


def _has_asset_failed(asset: ExportedAsset) -> bool:
    return (not asset.content and not asset.content_location) or asset.exception is not None


def next_delivery_date_display(subscription: Subscription) -> str:
    next_delivery_date = subscription.next_delivery_date
    return next_delivery_date.strftime("%A %B %d, %Y") if next_delivery_date is not None else "an upcoming date"


_OOM_MESSAGE_MARKER = "ran out of memory"
_OOM_EXCEPTION_TYPE = "ClickHouseQueryMemoryLimitExceeded"


def _is_oom_exception_text(exception_text: str | None) -> bool:
    return exception_text is not None and _OOM_MESSAGE_MARKER in exception_text.lower()


def subscription_asset_error_message(asset: ExportedAsset) -> str:
    # Recipients of scheduled subscriptions didn't author the query, so the OOM advice is
    # unactionable. Original text stays on asset.exception/exception_type for our own logs.
    is_oom_exception = asset.exception_type == _OOM_EXCEPTION_TYPE or _is_oom_exception_text(asset.exception)
    if asset.exception and not is_oom_exception:
        return asset.exception
    return ASSET_GENERATION_FAILED_MESSAGE


@frozen
class FailedAssetDetails:
    insight_name: str
    error_text: str


def failed_asset_details(asset: ExportedAsset) -> FailedAssetDetails:
    """The two pieces every channel renders for an asset that failed to generate. Callers own the
    markup, since Slack mrkdwn, Adaptive Card markdown and the email template all differ."""
    insight = asset.insight
    insight_name = (insight.name or insight.derived_name or "Unknown insight") if insight else "Unknown insight"
    if asset.exception:
        error_text = subscription_asset_error_message(asset)
        if len(error_text) > _MAX_ASSET_ERROR_LENGTH:
            error_text = error_text[:_MAX_ASSET_ERROR_LENGTH] + TRUNCATION_MARKER
    else:
        error_text = ASSET_GENERATION_FAILED_MESSAGE
    return FailedAssetDetails(insight_name=insight_name, error_text=error_text)


def subscription_support_url(resource_url: str) -> str:
    return f"{resource_url}#panel=support:bug:analytics_platform:high:true"


def summary_skipped_over_budget_message(billing_settings_link: str) -> str:
    return (
        "AI summary skipped. Your organization has reached its AI credit usage limit. "
        f"Increase the limit in {billing_settings_link} to resume summaries."
    )


def generate_assets(
    resource: Union[Subscription, SharingConfiguration],
    max_asset_count: int = MAX_INSIGHTS,
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
