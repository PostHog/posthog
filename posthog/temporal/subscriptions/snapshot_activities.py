import datetime as dt

import temporalio.activity
from prometheus_client import Counter
from structlog import get_logger

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.models.subscription import Subscription
from posthog.redis import get_async_client
from posthog.sync import database_sync_to_async
from posthog.temporal.subscriptions.change_summary_state import (
    compute_ttl_seconds,
    generate_state_key,
    load_insight_state,
    store_insight_state,
)
from posthog.temporal.subscriptions.llm_change_summary import generate_change_summary
from posthog.temporal.subscriptions.results_summarizer import build_results_summary
from posthog.temporal.subscriptions.types import SnapshotInsightsInputs, SnapshotInsightsResult

from ee.tasks.subscriptions.subscription_utils import DEFAULT_MAX_ASSET_COUNT

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


def _get_query_kind(query: dict | None) -> str:
    if not query:
        return "Unknown"
    source = query.get("source", query)
    return source.get("kind", "Unknown")


def _execute_insight_query(insight, team, dashboard=None):
    return calculate_for_query_based_insight(
        insight,
        team=team,
        dashboard=dashboard,
        execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        user=None,
    )


def _resolve_insights(subscription):
    dashboard = subscription.dashboard
    if dashboard:
        tiles = list(
            dashboard.tiles.select_related("insight").filter(insight__isnull=False, insight__deleted=False).all()
        )
        tiles.sort(
            key=lambda x: (
                (x.layouts or {}).get("sm", {}).get("y", 100),
                (x.layouts or {}).get("sm", {}).get("x", 100),
            )
        )
        insights = [tile.insight for tile in tiles if tile.insight]

        selected_ids = set(subscription.dashboard_export_insights.values_list("id", flat=True))
        if selected_ids:
            insights = [i for i in insights if i.id in selected_ids]

        return insights[:DEFAULT_MAX_ASSET_COUNT]
    elif subscription.insight:
        return [subscription.insight]
    return []


@temporalio.activity.defn
async def snapshot_subscription_insights(inputs: SnapshotInsightsInputs) -> SnapshotInsightsResult:
    await LOGGER.ainfo(
        "snapshot_subscription_insights.starting",
        subscription_id=inputs.subscription_id,
    )

    subscription = await database_sync_to_async(
        Subscription.objects.select_related("insight", "dashboard", "team").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)

    if not subscription.summary_enabled:
        await LOGGER.ainfo(
            "snapshot_subscription_insights.summary_disabled",
            subscription_id=inputs.subscription_id,
        )
        return SnapshotInsightsResult()

    team = subscription.team

    insights = await database_sync_to_async(_resolve_insights, thread_sensitive=False)(subscription)
    if not insights:
        await LOGGER.awarning(
            "snapshot_subscription_insights.no_insights",
            subscription_id=inputs.subscription_id,
        )
        return SnapshotInsightsResult()

    redis_client = get_async_client()
    ttl = compute_ttl_seconds(subscription.frequency, subscription.interval)
    now = dt.datetime.now(dt.UTC).isoformat()
    dashboard = subscription.dashboard

    previous_states: list[dict] = []
    current_states: list[dict] = []
    has_any_previous = False

    for i, insight in enumerate(insights):
        temporalio.activity.heartbeat(f"processing insight {i + 1}/{len(insights)}")
        key = generate_state_key(inputs.subscription_id, insight.id)

        previous = await load_insight_state(redis_client, key)
        if previous is not None:
            has_any_previous = True
            previous["insight_id"] = insight.id
            previous_states.append(previous)

        query_kind = _get_query_kind(insight.query)
        try:
            result = await database_sync_to_async(_execute_insight_query, thread_sensitive=False)(
                insight, team, dashboard
            )
            results_summary = build_results_summary(query_kind, result.result)
        except Exception as e:
            await LOGGER.awarning(
                "snapshot_subscription_insights.query_failed",
                subscription_id=inputs.subscription_id,
                insight_id=insight.id,
                error=str(e),
                exc_info=True,
            )
            results_summary = "Query execution failed"

        insight_name = insight.name or insight.derived_name or f"Insight {insight.id}"
        current_states.append(
            {
                "insight_id": insight.id,
                "insight_name": insight_name,
                "query_kind": query_kind,
                "query_definition": insight.query or {},
                "results_summary": results_summary,
                "timestamp": now,
            }
        )

    summary_text: str | None = None
    try:
        summary_text = await database_sync_to_async(generate_change_summary, thread_sensitive=False)(
            previous_states if has_any_previous else None,
            current_states,
            subscription_title=subscription.title,
            prompt_guide=subscription.summary_prompt_guide or "",
            team_id=inputs.team_id,
        )
        SUBSCRIPTION_SUMMARY_SUCCESS.inc()
    except Exception as e:
        error_msg = str(e)
        reason = "openai_key_missing" if "OPENAI_API_KEY" in error_msg else "llm_error"
        SUBSCRIPTION_SUMMARY_FAILURE.labels(reason=reason).inc()
        await LOGGER.aerror(
            "snapshot_subscription_insights.llm_summary_failed",
            subscription_id=inputs.subscription_id,
            error=error_msg,
            exc_info=True,
        )

    if summary_text is not None:
        for current in current_states:
            key = generate_state_key(inputs.subscription_id, current["insight_id"])
            state_to_store = {
                "schema_version": 1,
                "query_definition": current["query_definition"],
                "query_kind": current.get("query_kind", "Unknown"),
                "results_summary": current["results_summary"],
                "timestamp": current["timestamp"],
                "insight_name": current["insight_name"],
            }
            await store_insight_state(redis_client, key, state_to_store, ttl)

    await LOGGER.ainfo(
        "snapshot_subscription_insights.completed",
        subscription_id=inputs.subscription_id,
        insight_count=len(insights),
        has_previous=has_any_previous,
        has_summary=summary_text is not None,
    )

    return SnapshotInsightsResult(
        summary_text=summary_text,
        is_initial_summary=not has_any_previous,
    )
