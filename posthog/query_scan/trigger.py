"""Decide whether a finished run gets analyzed, print its SQL, and enqueue the job.

The runner calls this once per blocking run. Everything before the enqueue is cheap; the run's SQL
is printed only once a run crosses the floor, which costs a few milliseconds.

Nothing here may change what the person gets. The analysis is advice, so a printer, broker or Redis
failure drops the enqueue and reports a skip, never the query result.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, TypeGuard
from uuid import UUID

import structlog
from pydantic import BaseModel

from posthog.schema import HogQLFilters

from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.query_stats import QueryStats, RecordedExecution

from posthog.clickhouse.query_tagging import get_query_tag_value, is_api_key_access_method
from posthog.dataclasses import frozen
from posthog.models.user import User
from posthog.query_scan.flag import QueryScanFlag
from posthog.query_scan.slot import (
    claim_enqueue_budget,
    clear as clear_slot,
    get as get_slot,
    set_pending,
)
from posthog.query_scan.stub import stub_in_subqueries

logger = structlog.get_logger(__name__)

# Above this an EXPLAIN is unlikely to plan and the payload is not worth shipping to the worker.
MAX_SQL_BYTES = 100 * 1024
# The runner can fan an insight out into many series; the heaviest handful explains the run.
MAX_EXECUTIONS = 5
# Each subquery is explained on its own, so the cap is across the whole run, not per execution.
MAX_SUBQUERIES = 5

_SQL_QUERY_KIND = "HogQLQuery"

SkipReason = Literal[
    "flag_off",
    "below_floor",
    "api_key",
    "no_principal",
    "not_cacheable",
    "direct_connection",
    "rate_limited",
    "slot_exists",
    "nothing_to_analyze",
    "too_large",
    "enqueue_failed",
]


@frozen
class QueryScanTrigger:
    triggered: bool
    skipped_reason: SkipReason | None


FLAG_OFF = QueryScanTrigger(triggered=False, skipped_reason="flag_off")
NO_PRINCIPAL = QueryScanTrigger(triggered=False, skipped_reason="no_principal")


def is_analyzable_principal(user: object) -> TypeGuard[User]:
    """Whether the response may carry the scan summary.

    Only a real user row identifies a member of the project. A shared-link viewer reads the insight
    from outside it and must not be shown the project's data volume, so the summary stays off their
    response. The job itself no longer runs as any user.
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
    killed: bool = False,
) -> QueryScanTrigger:
    """Enqueue the analysis job for this run, unless one of the skip tests holds.

    The run's SQL is printed only on the enqueue path, because the runner calls this for every
    blocking run and most of them stop at the floor.
    """
    if flag is None or stats is None:
        return FLAG_OFF

    duration_ms = round(stats.duration_ms)
    if duration_ms < flag.floor_ms:
        return QueryScanTrigger(triggered=False, skipped_reason="below_floor")
    if is_api_key_access_method(get_query_tag_value("access_method")):
        # An API caller has no surface to read the advice on, so the analysis would only cost.
        return QueryScanTrigger(triggered=False, skipped_reason="api_key")
    if getattr(query, "connectionId", None):
        # A direct connection reads the external warehouse instead of ClickHouse, so the job
        # would park a pending slot for an analysis that cannot happen.
        return QueryScanTrigger(triggered=False, skipped_reason="direct_connection")
    if not cacheable:
        return QueryScanTrigger(triggered=False, skipped_reason="not_cacheable")
    if get_slot(team_id, cache_key, thresholds=flag.thresholds_fingerprint) is not None:
        return QueryScanTrigger(triggered=False, skipped_reason="slot_exists")
    if not claim_enqueue_budget(team_id):
        return QueryScanTrigger(triggered=False, skipped_reason="rate_limited")
    if not set_pending(team_id, cache_key, killed=killed):
        # Another slow run of the same query claimed the slot between the read above and here.
        return QueryScanTrigger(triggered=False, skipped_reason="slot_exists")

    executions, dropped_oversized = _print_executions(stats)
    if not executions:
        # Nothing printable to analyze: an oversized run, or one that bypassed the executor.
        clear_slot(team_id, cache_key)
        reason: SkipReason = "too_large" if dropped_oversized else "nothing_to_analyze"
        return QueryScanTrigger(triggered=False, skipped_reason=reason)

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
            killed=killed,
            query_kind=query_kind,
            open_filters_placeholder=_open_filters_placeholder(query, query_kind),
        )
    except Exception:
        # The broker can be down while ClickHouse is fine, and the result is not cached yet, so
        # failing here would throw away a run the person already waited for.
        logger.warning("query_scan_enqueue_failed", team_id=team_id, exc_info=True)
        # Left in place, the claim above reports a pending analysis no job is coming to fill.
        clear_slot(team_id, cache_key)
        return QueryScanTrigger(triggered=False, skipped_reason="enqueue_failed")
    return QueryScanTrigger(triggered=True, skipped_reason=None)


def _print_executions(stats: QueryStats) -> tuple[list[dict[str, Any]], bool]:
    """Print the heaviest executions of the run for the job to EXPLAIN.

    Each is printed as the original SQL, the same query with its ``IN`` subqueries stubbed, and each
    of those subqueries stubbed on its own, so the job can explain a run whose cost sits in a
    subquery. Returns the executions to enqueue and whether any was dropped for being too large.
    """
    heaviest = sorted(stats.executions, key=lambda execution: execution.rows_read, reverse=True)[:MAX_EXECUTIONS]
    printed: list[dict[str, Any]] = []
    dropped_oversized = False
    subquery_budget = MAX_SUBQUERIES
    for execution in heaviest:
        entry = _print_execution(execution, subquery_budget)
        if entry is None:
            dropped_oversized = True
            continue
        subquery_budget -= len(entry["subqueries"])
        printed.append(entry)
    return printed, dropped_oversized


def _print_execution(execution: RecordedExecution, subquery_budget: int) -> dict[str, Any] | None:
    """One execution as the job's payload entry, or None when it cannot or should not be shipped."""
    try:
        context = execution.context
        sql = print_prepared_ast(execution.tree, context, dialect="clickhouse")
        if len(sql.encode("utf-8")) > MAX_SQL_BYTES:
            return None
        stub = stub_in_subqueries(execution.tree)
        stubbed_sql = print_prepared_ast(stub.stubbed, context, dialect="clickhouse")
        subqueries = [
            print_prepared_ast(stub_in_subqueries(subquery).stubbed, context, dialect="clickhouse")
            for subquery in stub.subqueries[: max(subquery_budget, 0)]
        ]
        return {
            "sql": sql,
            "stubbed_sql": stubbed_sql,
            "subqueries": subqueries,
            # The Celery boundary is JSON, so the parameter values travel JSON-safe; the job hands
            # them back to `sync_execute`, whose substitution reads a datetime the same as its text.
            "values": _json_safe(context.values),
            "rows_read": execution.rows_read,
        }
    except Exception:
        # A tree that will not print is one the job could not EXPLAIN either. Drop it rather than
        # fail the run the person already waited for.
        logger.warning("query_scan_print_failed", exc_info=True)
        return None


def _json_safe(values: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(values, default=_json_default))


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (set, frozenset)):
        return list(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _open_filters_placeholder(query: BaseModel, query_kind: str | None) -> bool:
    """Whether a HogQLQuery left its date range to a ``{filters}`` placeholder that expanded to no
    bound, so the missing start date is on the insight rather than in the SQL. Every other kind
    carries no raw SQL, so this is false for them."""
    if query_kind != _SQL_QUERY_KIND:
        return False
    return _has_open_filters_placeholder(getattr(query, "query", "") or "", getattr(query, "filters", None))


def _has_open_filters_placeholder(query: str, filters: HogQLFilters | None) -> bool:
    """Whether the query asks for a date range through ``{filters}`` and nobody supplied one.

    The placeholder then expands to no bound at all, so the missing start date is on the insight
    rather than in the SQL. Only the predicate forms count: ``{filters.interval(...)}`` and
    ``{filters.breakdown(...)}`` substitute a value, so no date range can bound the query through
    them.
    """
    try:
        if not find_placeholders(parse_select(query)).has_date_filters:
            return False
    except Exception:
        return False
    date_range = filters.dateRange if filters else None
    if date_range is None:
        return True
    # "all" promises the whole table, so the placeholder still expands to no lower bound.
    date_from = None if date_range.date_from == "all" else date_range.date_from
    return not (date_from or date_range.date_to)
