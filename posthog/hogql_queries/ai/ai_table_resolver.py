from __future__ import annotations

from typing import TYPE_CHECKING, Any

from prometheus_client import Counter, Histogram

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.hogql_queries.ai.ai_column_rewriter import rewrite_expr_for_events_table, rewrite_query_for_events_table
from posthog.hogql_queries.ai.ai_property_rewriter import rewrite_expr_for_ai_events_table
from posthog.ph_client import feature_enabled_or_false

AI_EVENTS_QUERY_TOTAL = Counter(
    "posthog_ai_events_query_total",
    "AI observability queries routed by query_ai_events, by read-path outcome.",
    labelnames=["source"],
)

AI_EVENTS_QUERY_DURATION_SECONDS = Histogram(
    "posthog_ai_events_query_duration_seconds",
    "Wall-clock duration of AI observability query executions, by read-path source.",
    labelnames=["source"],
    buckets=(0.025, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

if TYPE_CHECKING:
    from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
    from posthog.hogql.modifiers import HogQLQueryModifiers
    from posthog.hogql.timings import HogQLTimings

    from posthog.clickhouse.client.connection import Workload
    from posthog.models import Team


class AIEventsUnavailableError(Exception):
    """The requested AI events could not be served from the dedicated ai_events table
    and the caller opted out of the events fallback (``fall_back_to_events=False``)."""


def is_ai_events_enabled(team: Team) -> bool:
    """Kill switch for ai_events table reads.

    When disabled, all single-trace runners skip the ai_events attempt
    and query the events table directly.
    """
    return feature_enabled_or_false(
        "ai-events-table-rollout",
        str(team.id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


class AIEventsExpiredError(AIEventsUnavailableError):
    """The requested AI events exist in the shared events table but have aged out of
    ai_events (past its retention TTL)."""


class AIEventsNotFoundError(AIEventsUnavailableError):
    """The requested AI events were not found in either ai_events or the shared events table."""


def query_ai_events(
    query: ast.SelectQuery | ast.SelectSetQuery,
    placeholders: dict[str, ast.Expr],
    team: Team,
    query_type: str,
    *,
    fall_back_to_events: bool = False,
    timings: HogQLTimings | None = None,
    modifiers: HogQLQueryModifiers | None = None,
    limit_context: LimitContext | None = None,
    settings: HogQLGlobalSettings | None = None,
    workload: Workload | None = None,
    events_fallback_extra_conditions: list[ast.Expr] | None = None,
) -> Any:
    """Execute a query written against the dedicated ai_events table.

    Queries should be written against ai_events using native column names. Placeholders
    may contain properties.$ai_* references (e.g. from property filters); they are
    rewritten to native columns for ai_events and back to properties.$ai_* when the query
    runs against the shared events table.

    ai_events has a 30-day retention TTL; the shared events table is long-lived but has the
    heavy AI columns stripped. When ai_events returns no rows:

    - ``fall_back_to_events=True``: re-run against events and return that result. Use this
      for paths that stay useful without the heavy columns (trace shape, costs, navigation).
    - ``fall_back_to_events=False`` (default): an events row would be useless to the caller,
      so events is probed only to classify the miss — raising :class:`AIEventsExpiredError`
      (the data aged past the TTL) or :class:`AIEventsNotFoundError` (it never existed).

    `events_fallback_extra_conditions` are ANDed into the WHERE clause only on the events
    fallback path, never on the ai_events query. Use this for filters the dedicated table
    doesn't need but the shared `events` table does — chiefly a timestamp bound, since the
    `events` sort key leads with timestamp and its session/trace skip indexes barely prune
    without one. Conditions are rewritten for the events table just like placeholders.

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
        tag_queries(ai_query_source="dedicated_table")
        ai_placeholders = {k: rewrite_expr_for_ai_events_table(v) for k, v in placeholders.items()}
        with AI_EVENTS_QUERY_DURATION_SECONDS.labels(source="dedicated_table").time():
            result = execute_hogql_query(query=query, placeholders=ai_placeholders, **kwargs)
        if result.results:
            AI_EVENTS_QUERY_TOTAL.labels(source="dedicated_table").inc()
            return result

        events_query = rewrite_query_for_events_table(query)
        if events_fallback_extra_conditions:
            rewritten_conditions = [rewrite_expr_for_events_table(c) for c in events_fallback_extra_conditions]
            events_query = _and_conditions_into_where(events_query, rewritten_conditions)
        events_placeholders = {k: rewrite_expr_for_events_table(v) for k, v in placeholders.items()}

        if fall_back_to_events:
            tag_queries(ai_query_source="shared_table_fallback")
            AI_EVENTS_QUERY_TOTAL.labels(source="shared_table_fallback").inc()
            with AI_EVENTS_QUERY_DURATION_SECONDS.labels(source="shared_table_fallback").time():
                return execute_hogql_query(query=events_query, placeholders=events_placeholders, **kwargs)

        # The caller can't use heavy-column-stripped events rows, so probe events solely to
        # tell "aged past the TTL" apart from "never existed" and raise the matching error.
        with AI_EVENTS_QUERY_DURATION_SECONDS.labels(source="retention_probe").time():
            probe = execute_hogql_query(query=events_query, placeholders=events_placeholders, **kwargs)
        if probe.results:
            tag_queries(ai_query_source="expired")
            AI_EVENTS_QUERY_TOTAL.labels(source="expired").inc()
            raise AIEventsExpiredError(f"AI events for {query_type} have aged past the ai_events retention window")
        tag_queries(ai_query_source="not_found")
        AI_EVENTS_QUERY_TOTAL.labels(source="not_found").inc()
        raise AIEventsNotFoundError(f"AI events for {query_type} were not found")


def _and_conditions_into_where(
    query: ast.SelectQuery | ast.SelectSetQuery, conditions: list[ast.Expr]
) -> ast.SelectQuery | ast.SelectSetQuery:
    """AND extra conditions into a query's WHERE clause.

    Only SelectQuery is supported — the only caller passing extra conditions builds a plain
    SELECT. A SelectSetQuery (UNION etc.) has no single WHERE to extend, so reject it loudly
    rather than silently dropping the conditions.
    """
    if not isinstance(query, ast.SelectQuery):
        raise NotImplementedError(
            f"events_fallback_extra_conditions is only supported for SelectQuery, got {type(query).__name__}"
        )
    all_exprs = ([query.where] if query.where is not None else []) + conditions
    query.where = all_exprs[0] if len(all_exprs) == 1 else ast.And(exprs=all_exprs)
    return query


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
