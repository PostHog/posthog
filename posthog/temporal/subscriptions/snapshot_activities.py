import re
import uuid

import temporalio.activity
from prometheus_client import Counter
from structlog import get_logger

from posthog.models import Insight
from posthog.models.subscription import Subscription, SubscriptionDelivery
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


def _get_query_kind_from_insight(insight: Insight) -> str:
    query = insight.query
    if not query:
        return "Unknown"
    source = query.get("source", query)
    return source.get("kind", "Unknown")


def _build_states_from_content_snapshot(
    content_snapshot: dict,
    insight_query_kinds: dict[int, str] | None = None,
    timestamp: str = "unknown",
) -> list[dict]:
    states: list[dict] = []
    for insight_snap in content_snapshot.get("insights", []):
        insight_id = insight_snap.get("id")
        insight_name = insight_snap.get("name", f"Insight {insight_id}")
        query_results = insight_snap.get("query_results")

        query_kind = (insight_query_kinds or {}).get(insight_id, "Unknown")

        if query_results and query_results.get("result"):
            results_summary = build_results_summary(query_kind, query_results["result"])
        else:
            error = insight_snap.get("query_error", {})
            results_summary = "Query failed" if error else "No results"

        states.append(
            {
                "insight_id": insight_id,
                "insight_name": insight_name,
                "query_kind": query_kind,
                "results_summary": results_summary,
                "timestamp": timestamp,
            }
        )
    return states


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


@temporalio.activity.defn
async def snapshot_subscription_insights(inputs: SnapshotInsightsInputs) -> SnapshotInsightsResult:
    await LOGGER.ainfo(
        "snapshot_subscription_insights.starting",
        subscription_id=inputs.subscription_id,
    )

    subscription = await database_sync_to_async(
        Subscription.objects.select_related("team__organization").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)

    if not subscription.summary_enabled:
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
    )
    if not current_states:
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

    await LOGGER.ainfo(
        "snapshot_subscription_insights.completed",
        subscription_id=inputs.subscription_id,
        insight_count=len(current_states),
        has_previous=previous_states is not None,
        has_summary=summary_text is not None,
    )

    return SnapshotInsightsResult(summary_text=summary_text)
