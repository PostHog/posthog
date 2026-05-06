from __future__ import annotations

from typing import TYPE_CHECKING, Any

import posthoganalytics
from prometheus_client import Counter, Histogram

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.hogql_queries.ai.ai_column_rewriter import rewrite_expr_for_events_table, rewrite_query_for_events_table
from posthog.hogql_queries.ai.ai_property_rewriter import rewrite_expr_for_ai_events_table

AI_EVENTS_QUERY_TOTAL = Counter(
    "posthog_ai_events_query_total",
    "LLM analytics queries routed by execute_with_ai_events_fallback, by read-path source.",
    labelnames=["source"],
)

AI_EVENTS_QUERY_DURATION_SECONDS = Histogram(
    "posthog_ai_events_query_duration_seconds",
    "Wall-clock duration of LLM analytics query executions, by read-path source. Used to compare dedicated_table vs shared_table latency.",
    labelnames=["source"],
    buckets=(0.025, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

if TYPE_CHECKING:
    from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
    from posthog.hogql.modifiers import HogQLQueryModifiers
    from posthog.hogql.timings import HogQLTimings

    from posthog.clickhouse.client.connection import Workload
    from posthog.models import Team


def is_ai_events_enabled(team: Team) -> bool:
    """Kill switch for ai_events table reads.

    When disabled, all single-trace runners skip the ai_events attempt
    and query the events table directly.
    """
    return posthoganalytics.feature_enabled(
        "ai-events-table-rollout",
        str(team.id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def execute_with_ai_events_fallback(
    query: ast.SelectQuery | ast.SelectSetQuery,
    placeholders: dict[str, ast.Expr],
    team: Team,
    query_type: str,
    timings: HogQLTimings | None = None,
    modifiers: HogQLQueryModifiers | None = None,
    limit_context: LimitContext | None = None,
    settings: HogQLGlobalSettings | None = None,
    workload: Workload | None = None,
) -> Any:
    """Execute a query written against ai_events, falling back to events if no results.

    Queries should be written against the ai_events table with native column names.
    Placeholders may contain properties.$ai_* references (e.g. from property filters)
    which are rewritten to native columns for ai_events and back for the events fallback.

    When the kill switch (is_ai_events_enabled) is off, skips the ai_events attempt entirely.

    `workload` should be specified explicitly for batch / scheduled callers (e.g. usage
    reports). Inside a Celery task the `task_prerun` signal sets `Workload.OFFLINE` on
    the thread default, but outside Celery (Django shell, pytest, management commands)
    that signal does not fire — so callers that must run on a specific pool should not
    rely on it implicitly.
    """
    kwargs: dict[str, Any] = {"query_type": query_type, "team": team}
    if timings is not None:
        kwargs["timings"] = timings
    if modifiers is not None:
        kwargs["modifiers"] = modifiers
    if limit_context is not None:
        kwargs["limit_context"] = limit_context
    if settings is not None:
        kwargs["settings"] = settings
    if workload is not None:
        kwargs["workload"] = workload

    with tags_context(product=Product.LLM_ANALYTICS):
        if is_ai_events_enabled(team):
            tag_queries(ai_query_source="dedicated_table")
            ai_placeholders = {k: rewrite_expr_for_ai_events_table(v) for k, v in placeholders.items()}
            with AI_EVENTS_QUERY_DURATION_SECONDS.labels(source="dedicated_table").time():
                result = execute_hogql_query(query=query, placeholders=ai_placeholders, **kwargs)
            # Fallback: if ai_events returned no rows, re-run on the shared events table.
            # This handles the rollout window where older data may only exist in the shared
            # table. Only ~4% of queries fall outside the dedicated table's 30-day TTL
            # (https://us.posthog.com/project/2/insights/39oE9bLO), so for populated teams
            # the fallback fires rarely. Legitimately-empty queries do incur a redundant
            # second round-trip — acceptable during rollout, removed when the flag is retired.
            if result.results:
                AI_EVENTS_QUERY_TOTAL.labels(source="dedicated_table").inc()
                return result
            tag_queries(ai_query_source="shared_table_fallback")
            AI_EVENTS_QUERY_TOTAL.labels(source="shared_table_fallback").inc()
            fallback_source = "shared_table_fallback"
        else:
            tag_queries(ai_query_source="shared_table")
            AI_EVENTS_QUERY_TOTAL.labels(source="shared_table").inc()
            fallback_source = "shared_table"

        events_query = rewrite_query_for_events_table(query)
        events_placeholders = {k: rewrite_expr_for_events_table(v) for k, v in placeholders.items()}
        with AI_EVENTS_QUERY_DURATION_SECONDS.labels(source=fallback_source).time():
            return execute_hogql_query(query=events_query, placeholders=events_placeholders, **kwargs)


# Canonical Python list. Node.js mirror: nodejs/src/ingestion/ai/process-ai-event.ts
AI_EVENT_NAMES = frozenset(
    {
        "$ai_generation",
        "$ai_span",
        "$ai_trace",
        "$ai_embedding",
        "$ai_metric",
        "$ai_feedback",
        "$ai_evaluation",
    }
)
