"""Decide whether a run gets analyzed, print its SQL, and enqueue the job.

The runner calls this once per blocking run. The SQL is printed only for a run over the flag's
``floor_ms`` or one ClickHouse stopped. A printer, broker or Redis failure drops the enqueue, never
the query result.
"""

from __future__ import annotations

import json
from typing import Any, Literal, TypeGuard

import structlog
from pydantic import BaseModel

from posthog.schema import BaseMathType, FunnelMathType, GroupMathType, RetentionType

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.query_stats import QueryStats, RecordedExecution

from posthog.clickhouse.query_tagging import Feature, get_query_tag_value, is_api_key_access_method
from posthog.models.user import User
from posthog.query_scan.event_filter import classify_event_filter
from posthog.query_scan.findings import SQL_QUERY_KIND
from posthog.query_scan.flag import QueryScanFlag
from posthog.query_scan.slot import (
    claim_enqueue_budget,
    clear as clear_slot,
    get as get_slot,
    set_pending,
)
from posthog.query_scan.stub import stub_in_subqueries

logger = structlog.get_logger(__name__)

# Above this an EXPLAIN is unlikely to plan and the payload is not worth shipping to the worker. The
# cap covers the SQL and its parameter values together, since one large literal can outweigh the
# SQL around it.
MAX_EXECUTION_BYTES = 100 * 1024
# The runner can fan an insight out into many series; the heaviest handful explains the run.
MAX_EXECUTIONS = 5
# Each subquery is explained on its own, so the cap is across the whole run, not per execution.
MAX_SUBQUERIES = 5

# Math that finds each person's or group's first event, so the read has to start at the project's
# first event whatever date range the insight has.
_FIRST_TIME_MATHS: frozenset[str] = frozenset(
    {
        BaseMathType.FIRST_TIME_FOR_USER,
        BaseMathType.FIRST_MATCHING_EVENT_FOR_USER,
        GroupMathType.FIRST_TIME_FOR_GROUP,
        GroupMathType.FIRST_MATCHING_EVENT_FOR_GROUP,
        FunnelMathType.FIRST_TIME_FOR_USER,
        FunnelMathType.FIRST_TIME_FOR_USER_WITH_FILTERS,
    }
)

SkipReason = Literal[
    "flag_off",
    "below_floor",
    "api_key",
    "no_principal",
    "no_clickhouse_query",
    "not_cacheable",
    "direct_connection",
    "rate_limited",
    "slot_exists",
    "nothing_to_analyze",
    "too_large",
    "enqueue_failed",
]


def _is_mcp_run() -> bool:
    """An MCP agent authenticates with a personal API key, but it does read the findings in the
    block above its results, so the skip for API callers with nowhere to read advice leaves it
    out."""
    return get_query_tag_value("feature") == Feature.MCP


def is_analyzable_principal(user: object) -> TypeGuard[User]:
    """Whether the response may carry the scan summary. Only a real user row is a member of the project;
    a shared-link viewer must not see the project's data volume.
    """
    return isinstance(user, User)


def maybe_trigger_query_scan(
    *,
    flag: QueryScanFlag | None,
    stats: QueryStats | None,
    team_id: int,
    cache_key: str,
    query: BaseModel,
    trigger: str,
    cacheable: bool,
    insight_id: int | None = None,
    dashboard_id: int | None = None,
    killed: bool = False,
    error_type: str | None = None,
) -> SkipReason | None:
    """Enqueue the analysis for this run. Returns why it was skipped, or None once the job is enqueued."""
    if flag is None or stats is None:
        return "flag_off"

    duration_ms = round(stats.duration_ms)
    # The floor leaves alone the runs nobody minded. Nobody gets a result from a run ClickHouse
    # stopped, however fast it died, so a stopped run is analyzed at any duration.
    if duration_ms < flag.floor_ms and not killed:
        return "below_floor"
    if is_api_key_access_method(get_query_tag_value("access_method")) and not _is_mcp_run():
        # An API caller has no surface to read the advice on, so the analysis would only cost.
        return "api_key"
    if getattr(query, "connectionId", None):
        # A direct connection reads the external warehouse instead of ClickHouse, so the job
        # would park a pending slot for an analysis that cannot happen.
        return "direct_connection"
    if not cacheable:
        return "not_cacheable"
    if get_slot(team_id, cache_key, thresholds=flag.thresholds_fingerprint) is not None:
        return "slot_exists"
    if not claim_enqueue_budget(team_id):
        return "rate_limited"
    if not set_pending(team_id, cache_key, thresholds=flag.thresholds_fingerprint, killed=killed):
        # Another slow run of the same query claimed the slot between the read above and here.
        return "slot_exists"

    executions = _print_executions(stats)
    if executions is None:
        # A selected execution could not be shipped, so analyzing the rest would advise on a run the
        # job never saw whole.
        clear_slot(team_id, cache_key, thresholds=flag.thresholds_fingerprint)
        return "too_large"
    if not executions:
        # The run had no executions to print: it bypassed the executor, or fanned out into none.
        clear_slot(team_id, cache_key, thresholds=flag.thresholds_fingerprint)
        return "nothing_to_analyze"

    kind = getattr(query, "kind", None)
    query_kind = str(kind) if kind is not None else None

    # A module-level import would close the runner, trigger, task, job, runner cycle.
    from posthog.tasks.query_scan import analyze_query_scan  # noqa: PLC0415

    try:
        analyze_query_scan.delay(
            team_id=team_id,
            cache_key=cache_key,
            executions=executions,
            rows_read=stats.rows_read,
            duration_ms=duration_ms,
            trigger=trigger,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
            killed=killed,
            error_type=error_type,
            query_kind=query_kind,
            open_filters_placeholder=_open_filters_placeholder(query),
            all_time=_all_time(query),
            all_history_by_design=_reads_all_history_by_design(query),
        )
    except Exception:
        # The broker can be down while ClickHouse is fine, and the result is not cached yet, so
        # failing here would throw away a run the person already waited for.
        logger.warning("query_scan_enqueue_failed", team_id=team_id, exc_info=True)
        # Left in place, the claim above reports a pending analysis no job is coming to fill.
        clear_slot(team_id, cache_key, thresholds=flag.thresholds_fingerprint)
        return "enqueue_failed"
    return None


def _print_executions(stats: QueryStats) -> list[dict[str, Any]] | None:
    """Print the heaviest executions for the job to EXPLAIN: each with its subqueries stubbed, and
    each subquery on its own. None when any of the heaviest could not be shipped, so the job never
    analyzes part of a run and advises as if it saw the whole. An empty list means the run carried no
    executions to print.
    """
    heaviest = sorted(stats.executions, key=lambda execution: execution.rows_read, reverse=True)[:MAX_EXECUTIONS]
    printed: list[dict[str, Any]] = []
    subquery_budget = MAX_SUBQUERIES
    for execution in heaviest:
        entry = _print_execution(execution, subquery_budget)
        if entry is None:
            return None
        subquery_budget -= len(entry["subqueries"])
        printed.append(entry)
    return printed


def _print_execution(execution: RecordedExecution, subquery_budget: int) -> dict[str, Any] | None:
    """One execution as the job's payload entry, or None when it cannot or should not be shipped."""
    try:
        context = execution.context
        stub = stub_in_subqueries(execution.tree)
        entry = {
            "stubbed_sql": print_prepared_ast(stub.stubbed, context, dialect="clickhouse"),
            "subqueries": [
                print_prepared_ast(stub_in_subqueries(subquery).stubbed, context, dialect="clickhouse")
                for subquery in stub.subqueries[: max(subquery_budget, 0)]
            ],
            # The parameter values travel as they are: Celery's JSON serializer round-trips the
            # datetimes, dates, UUIDs and decimals among them.
            "values": context.values,
            "rows_read": execution.rows_read,
            # The plan says whether ClickHouse pruned on `event`; the tree says why it could not.
            # Classify here, where the prepared tree is held; the job folds it into the plan.
            "event_filter": _event_filter_verdict(execution.tree),
        }
        if len(json.dumps(entry, default=str).encode("utf-8")) > MAX_EXECUTION_BYTES:
            return None
        return entry
    except Exception:
        # A tree that will not print is one the job could not EXPLAIN either. Dropping it drops the
        # run's analysis, never the query result the person already waited for.
        logger.warning("query_scan_print_failed", exc_info=True)
        return None


def _event_filter_verdict(tree: ast.Expr) -> dict[str, str | None] | None:
    """The tree's event-filter classification, JSON-safe, for the job to combine with the plan.

    A classifier failure ships None rather than dropping the execution, because the plan-only
    fallback still produces a finding. Reads that disagree ship None for the same reason.
    """
    try:
        outcome = classify_event_filter(tree)
    except Exception:
        logger.warning("query_scan_classify_failed", exc_info=True)
        return None
    if outcome is None:
        return None
    return {"classification": outcome.classification, "reason": outcome.reason}


def _source(query: BaseModel) -> BaseModel:
    """The query an insight node wraps, or the query itself."""
    return getattr(query, "source", None) or query


def _all_time(query: BaseModel) -> bool:
    """Whether the person chose the "All time" date range. The runner turns that into a bound at
    the project's first event, so the plan reports a timestamp filter and cannot tell on its own."""
    source = _source(query)
    date_range = getattr(source, "dateRange", None)
    if date_range is None:
        filters = getattr(source, "filters", None)
        date_range = getattr(filters, "dateRange", None)
    return getattr(date_range, "date_from", None) == "all"


def _reads_all_history_by_design(query: BaseModel) -> bool:
    """Whether the insight has to read from the project's first event whatever its date range: a
    first-time math or first-time retention finds each person's first event, so a start date would
    change the answer and no start-date advice can help.
    """
    source = _source(query)
    series = getattr(source, "series", None) or []
    if any(getattr(item, "math", None) in _FIRST_TIME_MATHS for item in series):
        return True
    retention_filter = getattr(source, "retentionFilter", None)
    return getattr(retention_filter, "retentionType", None) == RetentionType.RETENTION_FIRST_TIME


def _open_filters_placeholder(query: BaseModel) -> bool:
    """Whether a HogQLQuery asks for a date range through ``{filters}`` and nobody supplied a start
    date. Only the predicate forms count: ``{filters.interval(...)}`` and ``{filters.breakdown(...)}``
    substitute a value and cannot bound the query. False for every other kind, which carries no raw SQL.
    """
    if getattr(query, "kind", None) != SQL_QUERY_KIND:
        return False
    try:
        if not find_placeholders(parse_select(getattr(query, "query", "") or "")).has_date_filters:
            return False
    except Exception:
        return False
    date_range = getattr(getattr(query, "filters", None), "dateRange", None)
    date_from = getattr(date_range, "date_from", None)
    # "all" promises the whole table, so the placeholder still expands to no lower bound, and an end
    # date on its own bounds nothing at the start.
    return not date_from or date_from == "all"
