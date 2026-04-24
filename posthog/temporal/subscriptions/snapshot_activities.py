import re
import uuid
from typing import Any

import temporalio.activity
from prometheus_client import Counter
from structlog import get_logger

from posthog.models import Insight
from posthog.models.exported_asset import ExportedAsset
from posthog.models.subscription import Subscription, SubscriptionDelivery
from posthog.ph_client import ph_scoped_capture
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async
from posthog.temporal.subscriptions.llm_change_summary import generate_change_summary
from posthog.temporal.subscriptions.results_summarizer import build_results_summary
from posthog.temporal.subscriptions.types import SnapshotInsightsInputs, SnapshotInsightsResult

LOGGER = get_logger(__name__)

SUBSCRIPTION_SUMMARY_SUCCESS = Counter(
    "posthog_subscription_ai_summary_success_total",
    "AI summary successfully generated for a subscription delivery",
)
SUBSCRIPTION_SUMMARY_FAILURE = Counter(
    "posthog_subscription_ai_summary_failure_total",
    "AI summary generation failed for a subscription delivery",
    ["reason"],
)
SUBSCRIPTION_SUMMARY_SKIPPED_NO_AI_CONSENT = Counter(
    "posthog_subscription_ai_summary_skipped_no_ai_consent_total",
    "AI summary skipped because the organization has not approved AI data processing",
)
SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED = Counter(
    "posthog_subscription_ai_summary_image_skipped_total",
    "AI summary image attachment skipped for an insight",
    ["reason"],
)

MAX_SUMMARY_IMAGES = 6
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 16 * 1024 * 1024

_MAX_LOGGED_KEYS = 15


def _get_query_kind_from_insight(insight: Insight) -> str:
    query = insight.query
    if not query:
        return "Unknown"
    source = query.get("source", query)
    return source.get("kind", "Unknown")


def _extract_columns(query_results: Any) -> list[str] | None:
    """Coerce the raw `columns` payload to a trusted `list[str]`.

    Keeping the isinstance filtering here means `_summarize_generic` downstream
    can trust its input shape instead of re-validating each entry.
    """
    if not isinstance(query_results, dict):
        return None
    raw_columns = query_results.get("columns")
    if not isinstance(raw_columns, list):
        return None
    cleaned = [c for c in raw_columns if isinstance(c, str)]
    return cleaned or None


def _build_states_from_content_snapshot(
    content_snapshot: dict,
    insight_query_kinds: dict[int, str] | None = None,
    timestamp: str = "unknown",
    snapshot_role: str = "current",
) -> list[dict]:
    states: list[dict] = []
    for insight_snap in content_snapshot.get("insights", []):
        insight_id = insight_snap.get("id")
        insight_name = insight_snap.get("name", f"Insight {insight_id}")
        insight_description = insight_snap.get("description") or ""
        comparison_enabled = bool(insight_snap.get("comparison_enabled"))
        query_results = insight_snap.get("query_results")

        raw_query_error = insight_snap.get("query_error")
        query_error: dict | None = raw_query_error if isinstance(raw_query_error, dict) and raw_query_error else None
        malformed_query_error = raw_query_error is not None and not isinstance(raw_query_error, dict)

        query_kind = (insight_query_kinds or {}).get(insight_id, "Unknown")
        result_payload = query_results.get("result") if query_results else None
        columns = _extract_columns(query_results)

        if query_results and result_payload:
            results_summary = build_results_summary(query_kind, result_payload, columns=columns)
            fallback_reason: str | None = None
        elif query_error:
            results_summary = "Query failed"
            fallback_reason = "query_error"
        else:
            results_summary = "No results"
            fallback_reason = "no_query_results"

        _log_insight_state(
            insight_id=insight_id,
            snapshot_role=snapshot_role,
            query_kind=query_kind,
            result_payload=result_payload,
            query_error=query_error,
            malformed_query_error=malformed_query_error,
            fallback_reason=fallback_reason,
            results_summary_length=len(results_summary),
            timestamp=timestamp,
        )

        states.append(
            {
                "insight_id": insight_id,
                "insight_name": insight_name,
                "insight_description": insight_description,
                "query_kind": query_kind,
                "results_summary": results_summary,
                "timestamp": timestamp,
                "comparison_enabled": comparison_enabled,
            }
        )
    return states


def _log_insight_state(
    *,
    insight_id: int | None,
    snapshot_role: str,
    query_kind: str,
    result_payload: Any,
    query_error: dict | None,
    malformed_query_error: bool,
    fallback_reason: str | None,
    results_summary_length: int,
    timestamp: str,
) -> None:
    if malformed_query_error:
        query_error_type: str | None = "non_dict"
    elif query_error:
        query_error_type = query_error.get("type")
    else:
        query_error_type = None

    LOGGER.info(
        "subscription_summary.insight_state_built",
        insight_id=insight_id,
        snapshot_role=snapshot_role,
        query_kind=query_kind,
        result_shape=_describe_result_shape(result_payload),
        query_error_type=query_error_type,
        fallback_reason=fallback_reason,
        results_summary_length=results_summary_length,
        timestamp=timestamp,
    )


def _describe_result_shape(result: Any) -> dict[str, Any]:
    if result is None:
        return {"type": "none"}
    if isinstance(result, list):
        first_item_type: str | None = None
        first_item_keys: list[str] | None = None
        if result:
            first_item_type = type(result[0]).__name__
            if isinstance(result[0], dict):
                first_item_keys = sorted(result[0].keys())[:_MAX_LOGGED_KEYS]
        return {
            "type": "list",
            "length": len(result),
            "first_item_type": first_item_type,
            "first_item_keys": first_item_keys,
        }
    if isinstance(result, dict):
        return {"type": "dict", "keys": sorted(result.keys())[:_MAX_LOGGED_KEYS]}
    return {"type": type(result).__name__}


def _get_delivery_by_id(delivery_id: str) -> SubscriptionDelivery | None:
    try:
        return SubscriptionDelivery.objects.get(pk=uuid.UUID(delivery_id))
    except (SubscriptionDelivery.DoesNotExist, ValueError):
        return None


def _get_previous_delivery(subscription_id: int, exclude_delivery_id: str | None = None) -> SubscriptionDelivery | None:
    qs = SubscriptionDelivery.objects.filter(
        subscription_id=subscription_id,
        status=SubscriptionDelivery.Status.COMPLETED,
        content_snapshot__isnull=False,
    ).order_by("-created_at")
    if exclude_delivery_id:
        try:
            qs = qs.exclude(pk=uuid.UUID(exclude_delivery_id))
        except ValueError:
            pass
    return qs.first()


def _get_insight_query_kinds(insight_ids: list[int]) -> dict[int, str]:
    insights = Insight.objects.filter(id__in=insight_ids).only("id", "query")
    result: dict[int, str] = {}
    for insight in insights:
        result[insight.id] = _get_query_kind_from_insight(insight)
    return result


def _sanitize_prompt_guide(prompt_guide: str) -> str:
    return re.sub(r"</?[a-zA-Z_][^>]*>", "", prompt_guide)


def _capture_summary_generated_event(
    subscription: Subscription,
    *,
    delivery_id: str | None,
    summary_text: str,
    insight_count: int,
    image_count: int,
    has_previous_snapshot: bool,
) -> None:
    """Fire a product analytics event when a summary has been successfully generated.

    Recipients aren't identifiable (email addresses, Slack channels, webhook URLs
    have no distinct_id), so we attribute the event to the subscription creator —
    falling back to a `team_<id>` string when the creator has been removed so
    system-generated deliveries don't pollute real-user counts in analytics.
    Wrapped in a broad except so a capture failure can never bubble up and
    poison an otherwise successful activity run.
    """
    try:
        if subscription.created_by and subscription.created_by.distinct_id:
            distinct_id: str = subscription.created_by.distinct_id
        else:
            distinct_id = f"team_{subscription.team_id}"
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=distinct_id,
                event="subscription_ai_summary_generated",
                properties={
                    "subscription_id": subscription.id,
                    "team_id": subscription.team_id,
                    "delivery_id": delivery_id,
                    "target_type": subscription.target_type,
                    "insight_count": insight_count,
                    "image_count": image_count,
                    "has_previous_snapshot": has_previous_snapshot,
                    "summary_text_length": len(summary_text),
                    "resource_type": "dashboard" if subscription.dashboard_id else "insight",
                },
                groups={"organization": str(subscription.team.organization_id)},
            )
    except Exception:
        LOGGER.warning(
            "subscription_ai_summary_generated.capture_failed",
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=delivery_id,
            exc_info=True,
        )


def _load_insight_images(exported_asset_ids: list[int], team_id: int) -> dict[int, bytes]:
    if not exported_asset_ids:
        return {}

    assets_by_id = {
        asset.id: asset
        for asset in ExportedAsset.objects.filter(
            pk__in=exported_asset_ids,
            team_id=team_id,
            export_format=ExportedAsset.ExportFormat.PNG,
        ).only("id", "insight_id", "content", "content_location")
    }

    images: dict[int, bytes] = {}
    total_bytes = 0
    for asset_id in exported_asset_ids:
        if len(images) >= MAX_SUMMARY_IMAGES:
            break
        asset = assets_by_id.get(asset_id)
        if asset is None:
            SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="not_found").inc()
            continue
        if asset.insight_id is None:
            SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="no_insight_id").inc()
            continue
        if asset.insight_id in images:
            SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="duplicate_insight").inc()
            continue

        content: bytes | None = asset.content
        if not content and asset.content_location:
            try:
                content = object_storage.read_bytes(asset.content_location, missing_ok=True)
            except Exception:
                SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="storage_error").inc()
                continue

        if not content:
            SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="no_content").inc()
            continue

        if len(content) > MAX_IMAGE_BYTES:
            SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="too_large").inc()
            continue

        if total_bytes + len(content) > MAX_TOTAL_IMAGE_BYTES:
            SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="total_bytes_exceeded").inc()
            continue

        images[asset.insight_id] = content
        total_bytes += len(content)

    return images


@temporalio.activity.defn
async def snapshot_subscription_insights(inputs: SnapshotInsightsInputs) -> SnapshotInsightsResult:
    try:
        return await _run_snapshot_subscription_insights(inputs)
    except Exception:
        # The metric survives Kafka log producer init failure in `configure_logger`;
        # the log emission may not, so both are deliberate.
        SUBSCRIPTION_SUMMARY_FAILURE.labels(reason="activity_error").inc()
        await LOGGER.aexception(
            "snapshot_subscription_insights.failed",
            subscription_id=inputs.subscription_id,
            delivery_id=inputs.delivery_id,
        )
        raise


async def _run_snapshot_subscription_insights(inputs: SnapshotInsightsInputs) -> SnapshotInsightsResult:
    await LOGGER.ainfo(
        "snapshot_subscription_insights.starting",
        subscription_id=inputs.subscription_id,
    )

    subscription = await database_sync_to_async(
        Subscription.objects.select_related("team__organization", "created_by").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)

    if not subscription.summary_enabled:
        await LOGGER.ainfo(
            "snapshot_subscription_insights.skipped_summary_disabled",
            subscription_id=inputs.subscription_id,
        )
        return SnapshotInsightsResult()

    if not subscription.team.organization.is_ai_data_processing_approved:
        SUBSCRIPTION_SUMMARY_SKIPPED_NO_AI_CONSENT.inc()
        await LOGGER.ainfo(
            "snapshot_subscription_insights.skipped_no_ai_consent",
            subscription_id=inputs.subscription_id,
            organization_id=str(subscription.team.organization_id),
        )
        return SnapshotInsightsResult()

    if not inputs.delivery_id:
        return SnapshotInsightsResult()

    temporalio.activity.heartbeat("loading current delivery")
    current_delivery = await database_sync_to_async(_get_delivery_by_id, thread_sensitive=False)(inputs.delivery_id)
    if not current_delivery or not current_delivery.content_snapshot:
        await LOGGER.awarning(
            "snapshot_subscription_insights.no_content_snapshot",
            subscription_id=inputs.subscription_id,
        )
        return SnapshotInsightsResult()

    content_snapshot = current_delivery.content_snapshot

    temporalio.activity.heartbeat("resolving query kinds")
    insight_ids = [snap.get("id") for snap in content_snapshot.get("insights", []) if snap.get("id")]
    insight_query_kinds = await database_sync_to_async(_get_insight_query_kinds, thread_sensitive=False)(insight_ids)

    temporalio.activity.heartbeat("building current states")
    current_states = _build_states_from_content_snapshot(
        content_snapshot,
        insight_query_kinds=insight_query_kinds,
        timestamp=current_delivery.created_at.isoformat() if current_delivery.created_at else "unknown",
        snapshot_role="current",
    )
    if not current_states:
        await LOGGER.awarning(
            "snapshot_subscription_insights.no_current_states",
            subscription_id=inputs.subscription_id,
            insight_count=len(content_snapshot.get("insights", [])),
        )
        return SnapshotInsightsResult()

    temporalio.activity.heartbeat("loading previous delivery")
    previous_delivery = await database_sync_to_async(_get_previous_delivery, thread_sensitive=False)(
        inputs.subscription_id, exclude_delivery_id=inputs.delivery_id
    )

    previous_states: list[dict] | None = None
    if previous_delivery and previous_delivery.content_snapshot:
        previous_states = _build_states_from_content_snapshot(
            previous_delivery.content_snapshot,
            insight_query_kinds=insight_query_kinds,
            timestamp=previous_delivery.created_at.isoformat() if previous_delivery.created_at else "unknown",
            snapshot_role="previous",
        )

    temporalio.activity.heartbeat("loading insight images")
    insight_images: dict[int, bytes] = {}
    if inputs.exported_asset_ids:
        try:
            insight_images = await database_sync_to_async(_load_insight_images, thread_sensitive=False)(
                inputs.exported_asset_ids, inputs.team_id
            )
        except Exception as e:
            SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="load_failed").inc()
            await LOGGER.awarning(
                "snapshot_subscription_insights.image_load_failed",
                subscription_id=inputs.subscription_id,
                error=str(e),
                exc_info=True,
            )

    summary_text: str | None = None
    try:
        temporalio.activity.heartbeat("generating LLM summary")
        prompt_guide = _sanitize_prompt_guide(subscription.summary_prompt_guide or "")
        summary_text = await database_sync_to_async(generate_change_summary, thread_sensitive=False)(
            previous_states,
            current_states,
            subscription_title=subscription.title,
            prompt_guide=prompt_guide,
            team=subscription.team,
            delivery_id=inputs.delivery_id,
            insight_images=insight_images or None,
        )
        SUBSCRIPTION_SUMMARY_SUCCESS.inc()
    except Exception as e:
        error_msg = str(e)
        reason = "llm_error"
        SUBSCRIPTION_SUMMARY_FAILURE.labels(reason=reason).inc()
        await LOGGER.aerror(
            "snapshot_subscription_insights.llm_summary_failed",
            subscription_id=inputs.subscription_id,
            error=error_msg,
            exc_info=True,
        )

    if summary_text:
        await database_sync_to_async(_capture_summary_generated_event, thread_sensitive=False)(
            subscription,
            delivery_id=inputs.delivery_id,
            summary_text=summary_text,
            insight_count=len(current_states),
            image_count=len(insight_images),
            has_previous_snapshot=previous_states is not None,
        )

    await LOGGER.ainfo(
        "snapshot_subscription_insights.completed",
        subscription_id=inputs.subscription_id,
        insight_count=len(current_states),
        image_count=len(insight_images),
        image_bytes_total=sum(len(b) for b in insight_images.values()),
        has_previous=previous_states is not None,
        has_summary=summary_text is not None,
    )

    return SnapshotInsightsResult(summary_text=summary_text)
