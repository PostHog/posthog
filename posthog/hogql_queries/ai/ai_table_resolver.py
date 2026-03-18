from __future__ import annotations

from typing import TYPE_CHECKING, Any

import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.ai.ai_column_rewriter import rewrite_expr_for_events_table, rewrite_query_for_events_table
from posthog.hogql_queries.ai.ai_property_rewriter import rewrite_expr_for_ai_events_table

if TYPE_CHECKING:
    from posthog.hogql.constants import LimitContext
    from posthog.hogql.modifiers import HogQLQueryModifiers
    from posthog.hogql.timings import HogQLTimings

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
) -> Any:
    """Execute a query written against ai_events, falling back to events if no results.

    Queries should be written against the ai_events table with native column names.
    Placeholders may contain properties.$ai_* references (e.g. from property filters)
    which are rewritten to native columns for ai_events and back for the events fallback.

    When the kill switch (is_ai_events_enabled) is off, skips the ai_events attempt entirely.
    """
    kwargs: dict[str, Any] = {"query_type": query_type, "team": team}
    if timings is not None:
        kwargs["timings"] = timings
    if modifiers is not None:
        kwargs["modifiers"] = modifiers
    if limit_context is not None:
        kwargs["limit_context"] = limit_context

    with tags_context(product=Product.LLM_ANALYTICS):
        if is_ai_events_enabled(team):
            ai_placeholders = {k: rewrite_expr_for_ai_events_table(v) for k, v in placeholders.items()}
            result = execute_hogql_query(query=query, placeholders=ai_placeholders, **kwargs)
            if result.results:
                return result

        events_query = rewrite_query_for_events_table(query)
        events_placeholders = {k: rewrite_expr_for_events_table(v) for k, v in placeholders.items()}
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
