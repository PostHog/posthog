"""The query scan job, kept out of Celery so a test can call it directly.

It asks ClickHouse how it planned the run's SQL, reads findings and shares off the plan, and stores
the result in the scan slot. It runs EXPLAINs only, on the cluster the run went to, and runs the
independent ones together.
"""

from __future__ import annotations

import threading
import contextvars
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from enum import StrEnum
from time import perf_counter
from typing import Any, TypeVar, get_args

import structlog
from celery.exceptions import SoftTimeLimitExceeded

from posthog.schema import QueryScanAnalysis, QueryScanWarning

from posthog.hogql import query_stats

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture
from posthog.query_scan.analyze import PlanSet, QueryScanResult, analyze
from posthog.query_scan.event_filter import (
    EventFilterClass,
    EventFilterOutcome,
    EventFilterReason,
    combine_event_filter,
)
from posthog.query_scan.explain import QueryPlan, TimestampBounds, parse_query_plan
from posthog.query_scan.flag import get_query_scan_flag
from posthog.query_scan.slot import (
    clear as clear_slot,
    set_done,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")

EXPLAIN_MAX_SECONDS = 10
TABLE_AVERAGES_MAX_SECONDS = 5
# The trigger ships five executions with five subqueries at most, so one job plans seventeen
# queries at the outside. The cap keeps it from opening that many connections at once.
MAX_EXPLAIN_WORKERS = 8
# Analyses run in this process for callers that wait. One that passes its deadline runs on
# behind its response and still counts, so a burst of slow API runs across teams cannot pile
# up threads and connections here; past the cap the trigger enqueues the run instead.
MAX_INLINE_ANALYSES = 4
_inline_slots = threading.BoundedSemaphore(MAX_INLINE_ANALYSES)

# The two events tables and the three persons tables the persons gate compares in rows.
_ROW_AVERAGE_TABLES = (
    "sharded_events",
    "sharded_events_json",
    "person",
    "person_distinct_id2",
    "person_distinct_id_overrides",
)

# The tree verdict the trigger ships per execution. A payload outside these leaves the event filter
# to the plan alone, the same as a payload that carried no verdict.
_EVENT_FILTER_CLASSES = get_args(EventFilterClass)
_EVENT_FILTER_REASONS = get_args(EventFilterReason)


@frozen
class Execution:
    """One printed execution of the run, as the trigger enqueued it. ``event_filter`` is the tree
    verdict the trigger classified, or None when it shipped nothing.
    """

    stubbed_sql: str
    subqueries: tuple[str, ...]
    values: dict[str, Any]
    rows_read: int
    event_filter: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Execution:
        return cls(
            stubbed_sql=payload["stubbed_sql"],
            subqueries=tuple(payload.get("subqueries") or ()),
            values=payload.get("values") or {},
            rows_read=payload.get("rows_read") or 0,
            event_filter=payload.get("event_filter"),
        )


@frozen
class QueryScanJob:
    """One run to analyze, as the trigger printed it."""

    team: Team
    cache_key: str
    executions: tuple[Execution, ...]
    rows_read: int
    duration_ms: int
    trigger: str
    query_kind: str | None
    open_filters_placeholder: bool
    insight_id: int | None = None
    dashboard_id: int | None = None
    killed: bool = False
    error_type: str | None = None
    all_time: bool = False
    all_history_by_design: bool = False
    workload: Workload = Workload.OFFLINE
    # None for a run analyzed on the worker, where no caller waits for it.
    inline_deadline_ms: int | None = None


def run_query_scan(job: QueryScanJob) -> None:
    """Analyze one run and store the result. Never raises, and never retries: the next slow
    run of the same query enqueues a new job."""
    started = perf_counter()
    try:
        _run(job, started)
    except SoftTimeLimitExceeded:
        # The task handles its own timeout; letting it propagate leaves the pending slot to expire.
        raise
    except Exception as error:
        capture_exception(error, {"team_id": job.team.pk, "cache_key": job.cache_key, "context": "query_scan_job"})


class InlineOutcome(StrEnum):
    """What an analysis run before the response did: stored in time, still running past the
    deadline, or declined because this process already runs as many as it may."""

    STORED = "stored"
    PENDING = "pending"
    DECLINED = "declined"


def run_query_scan_inline(job: QueryScanJob) -> InlineOutcome:
    """Analyze ``job`` while its caller waits, for up to ``job.inline_deadline_ms``.

    Past the deadline the thread runs on and stores the analysis, so the response goes out with the
    slot pending and the next read of the slot serves the findings. Nothing is enqueued again, which
    would plan the same run twice.
    """
    if not _inline_slots.acquire(blocking=False):
        return InlineOutcome.DECLINED
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="query_scan_inline")
    try:
        future = _submit_in_context(pool, _run_and_free_the_slot, job)
    except BaseException:
        _inline_slots.release()
        raise
    finally:
        # The request returns while the analysis finishes; the thread ends on its own.
        pool.shutdown(wait=False)
    try:
        future.result(timeout=(job.inline_deadline_ms or 0) / 1000)
    except TimeoutError:
        return InlineOutcome.PENDING
    return InlineOutcome.STORED


def _run_and_free_the_slot(job: QueryScanJob) -> None:
    try:
        run_query_scan(job)
    finally:
        _inline_slots.release()


def _submit_in_context(pool: ThreadPoolExecutor, fn: Callable[..., T], *args: Any) -> Future[T]:
    """Run ``fn`` on the pool under a copy of the caller's context, so the query tags reach the
    thread, and outside the caller's query-stats scope, so the EXPLAINs do not count as the run's
    own reads. A new thread starts with an empty context, and one Context object cannot be entered
    by two threads at once, so each task gets its own copy."""
    context = contextvars.copy_context()

    def run_detached() -> T:
        with query_stats.detached():
            return fn(*args)

    return pool.submit(lambda: context.run(run_detached))


class _Planner:
    """The job's EXPLAINs, run on the pool against the cluster the run went to."""

    def __init__(self, pool: ThreadPoolExecutor, *, team_id: int, workload: Workload) -> None:
        self._pool = pool
        self._team_id = team_id
        self._workload = workload

    def table_row_averages(self) -> Future[dict[str, float]]:
        return _submit_in_context(self._pool, _table_row_averages, self._team_id, self._workload)

    def team_granules(self) -> Future[int | None]:
        return _submit_in_context(self._pool, _team_granules, self._team_id, self._workload)

    def plan(self, sql: str, values: dict[str, Any]) -> Future[QueryPlan | None]:
        return _submit_in_context(self._pool, _plan, sql, values, self._team_id, self._workload)

    def range_granules(self, bounds: TimestampBounds) -> Future[int | None]:
        return _submit_in_context(self._pool, _range_granules, self._team_id, bounds, self._workload)


def _run(job: QueryScanJob, started: float) -> None:
    flag = get_query_scan_flag(job.team)
    if flag is None:
        # The flag went off between the enqueue and now. Leave the pending slot to expire.
        return

    pool = ThreadPoolExecutor(max_workers=MAX_EXPLAIN_WORKERS, thread_name_prefix="query_scan")
    try:
        planner = _Planner(pool, team_id=job.team.pk, workload=job.workload)
        # The row average is a table-wide property and the team denominator is the same for every
        # execution, so each runs once.
        table_row_averages = planner.table_row_averages()
        team_granules = planner.team_granules()
        outers = [planner.plan(execution.stubbed_sql, execution.values) for execution in job.executions]
        subqueries = [
            [planner.plan(sql, execution.values) for sql in execution.subqueries] for execution in job.executions
        ]
        # The range denominator reads its bounds off the outer plan, so it waits for that one.
        # Executions over the same range share one EXPLAIN.
        bounds = [_timestamp_bounds(outer.result()) for outer in outers]
        range_granules = {
            execution_bounds: planner.range_granules(execution_bounds)
            for execution_bounds in set(bounds)
            if execution_bounds is not None
        }

        results: list[QueryScanResult] = []
        for execution, outer, execution_subqueries, execution_bounds in zip(
            job.executions, outers, subqueries, bounds, strict=True
        ):
            plans = PlanSet(
                outer=outer.result(),
                subqueries=tuple(
                    plan for plan in (future.result() for future in execution_subqueries) if plan is not None
                ),
                team_granules=team_granules.result(),
                # With no bound the range is all time, so it equals the team denominator.
                range_granules=(
                    range_granules[execution_bounds].result()
                    if execution_bounds is not None
                    else team_granules.result()
                ),
            )
            results.append(
                analyze(
                    plans,
                    flag,
                    query_kind=job.query_kind or "",
                    open_filters_placeholder=job.open_filters_placeholder,
                    all_time=job.all_time,
                    all_history_by_design=job.all_history_by_design,
                    event_filter=_combined_event_filter(execution, outer.result()),
                    table_row_averages=table_row_averages.result(),
                )
            )
    finally:
        # An analysis that stops early drops the EXPLAINs it has not started; the running ones
        # finish under their own time limit.
        pool.shutdown(wait=True, cancel_futures=True)

    merged = _merge(results, job.executions)
    # Stored under the flag in force now. A pending claim left under other thresholds expires on its
    # own key.
    if merged.explain_ok:
        set_done(
            job.team.pk,
            job.cache_key,
            thresholds=flag.thresholds_fingerprint,
            analysis=QueryScanAnalysis(
                findings=list(merged.findings), range_share=merged.range_share, project_share=merged.project_share
            ),
        )
    else:
        # A slot stored with no plan behind it would say "nothing to fix" for 30 days, so the claim
        # goes and the next slow run analyzes again.
        clear_slot(job.team.pk, job.cache_key, thresholds=flag.thresholds_fingerprint)
    _report(job, merged, flag_event_ratio=flag.event_ratio, job_ms=round((perf_counter() - started) * 1000))


def _plan(sql: str, values: dict[str, Any], team_id: int, workload: Workload) -> QueryPlan | None:
    """The plan for one stubbed query, or None when its EXPLAIN did not return one.

    Only stubbed SQL reaches EXPLAIN, because it runs every IN subquery it is given. A rows cap
    cannot guard the exact SQL, since ClickHouse checks it against the planned read's own estimate.
    """
    rows = _explain(sql, values, team_id, workload)
    if rows is None:
        return None
    return parse_query_plan(rows[0][0])


def _combined_event_filter(execution: Execution, outer: QueryPlan | None) -> EventFilterOutcome | None:
    """The tree verdict the trigger shipped, folded with the outer plan's key use. None when it shipped
    none, so the plan alone decides.
    """
    payload = execution.event_filter
    if not payload:
        return None
    classification = payload.get("classification")
    if classification is None or classification not in _EVENT_FILTER_CLASSES:
        return None
    reason = payload.get("reason")
    outcome = EventFilterOutcome(
        classification=classification,
        reason=reason if reason in _EVENT_FILTER_REASONS else None,
    )
    return combine_event_filter(outcome, outer)


def _team_granules(team_id: int, workload: Workload) -> int | None:
    """The team's whole data on the initiator shard."""
    return _denominator_granules(
        _explain(
            "SELECT uuid FROM events WHERE team_id = %(scan_team_id)s", {"scan_team_id": team_id}, team_id, workload
        )
    )


def _timestamp_bounds(outer: QueryPlan | None) -> TimestampBounds | None:
    """The bounds the outer plan's Min-Max step reported, or None when the read is open on both sides."""
    events_read = outer.heaviest_events_read() if outer is not None else None
    bounds = events_read.timestamp_bounds() if events_read is not None else None
    if bounds is None or (bounds.lower is None and bounds.upper is None):
        return None
    return bounds


def _range_granules(team_id: int, bounds: TimestampBounds, workload: Workload) -> int | None:
    """The team's granules over the run's date range."""
    return _denominator_granules(_explain_range(team_id, bounds, workload))


def _explain_range(team_id: int, bounds: TimestampBounds, workload: Workload) -> list[Any] | None:
    conditions = ["team_id = %(scan_team_id)s"]
    values: dict[str, Any] = {"scan_team_id": team_id}
    if bounds.lower is not None:
        conditions.append("timestamp >= toDateTime(%(scan_lower)s)")
        values["scan_lower"] = bounds.lower
    if bounds.upper is not None:
        conditions.append("timestamp < toDateTime(%(scan_upper)s)")
        values["scan_upper"] = bounds.upper
    # A bare count() can be answered from a count projection with no table read in the plan, so the
    # denominator selects a column; EXPLAIN reads nothing either way.
    return _explain("SELECT uuid FROM events WHERE " + " AND ".join(conditions), values, team_id, workload)


def _denominator_granules(rows: list[Any] | None) -> int | None:
    if rows is None:
        return None
    events_read = parse_query_plan(rows[0][0]).heaviest_events_read()
    return events_read.selected_granules() if events_read is not None else None


def _table_row_averages(team_id: int, workload: Workload) -> dict[str, float]:
    """Average rows per granule per table, from `system.parts` metadata. A failure yields an empty map
    rather than failing the analysis: the persons gate then falls back to raw granules.
    """
    try:
        with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.QUERY_SCAN):
            rows = sync_execute(
                "SELECT table, sum(rows) / sum(marks) FROM system.parts WHERE active AND table IN %(tables)s GROUP BY table",
                {"tables": list(_ROW_AVERAGE_TABLES)},
                settings={"max_execution_time": TABLE_AVERAGES_MAX_SECONDS},
                workload=workload,
                team_id=team_id,
                readonly=True,
            )
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.warning("query_scan_table_averages_failed", team_id=team_id, exc_info=True)
        return {}
    return {table: float(average) for table, average in rows if average is not None and float(average) > 0}


def _explain(sql: str, values: dict[str, Any], team_id: int, workload: Workload) -> list[Any] | None:
    """EXPLAIN on the run's cluster. None on any failure, which fails that plan closed."""
    try:
        with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.QUERY_SCAN):
            # nosemgrep: clickhouse-fstring-param-audit - sql is compiled from the HogQL AST by the printer, and its values stay parameterized
            rows = sync_execute(
                f"EXPLAIN indexes = 1, json = 1 {sql}",
                values,
                settings={"max_execution_time": EXPLAIN_MAX_SECONDS},
                workload=workload,
                team_id=team_id,
                readonly=True,
            )
        return rows
    except SoftTimeLimitExceeded:
        # Never swallow the task's timeout as an explain failure; the task leaves the slot pending.
        raise
    except Exception:
        logger.warning("query_scan_explain_failed", team_id=team_id, exc_info=True)
        return None


def _merge(results: list[QueryScanResult], executions: tuple[Execution, ...]) -> QueryScanResult:
    """One result from the executions the job analyzed: findings deduplicated by kind and reason, and
    the shares from the execution that read the most rows."""
    findings: list[QueryScanWarning] = []
    seen: set[tuple[str, str]] = set()
    for result in results:
        for finding in result.findings:
            key = (str(finding.kind), str(finding.reason))
            if key not in seen:
                seen.add(key)
                findings.append(finding)

    heaviest = _heaviest_result(results, executions)
    return QueryScanResult(
        findings=findings,
        # A person reads the advice as if it covered the whole run, so one unplanned execution
        # fails the run, the way the trigger drops a run with one execution it cannot ship.
        explain_ok=all(result.explain_ok for result in results),
        range_share=heaviest.range_share if heaviest is not None else None,
        project_share=heaviest.project_share if heaviest is not None else None,
    )


def _heaviest_result(results: list[QueryScanResult], executions: tuple[Execution, ...]) -> QueryScanResult | None:
    if not results:
        return None
    return max(zip(results, executions, strict=True), key=lambda pair: pair[1].rows_read)[0]


def _report(job: QueryScanJob, merged: QueryScanResult, *, flag_event_ratio: float, job_ms: int) -> None:
    """Send `query scan analyzed`, findings or not: a run with no findings is what says which check to
    write next.
    """
    inline = job.inline_deadline_ms is not None
    properties = {
        "cache_key": job.cache_key,
        "insight_id": job.insight_id,
        "dashboard_id": job.dashboard_id,
        "query_kind": job.query_kind,
        "trigger": job.trigger,
        "rows_read": job.rows_read,
        "duration_ms": job.duration_ms,
        "range_share": merged.range_share,
        "project_share": merged.project_share,
        "event_ratio": flag_event_ratio,
        "explain_ok": merged.explain_ok,
        "finding_kinds": merged.finding_kinds(),
        "killed": job.killed,
        "error_type": job.error_type,
        "job_ms": job_ms,
        "workload": job.workload.value,
        "inline": inline,
        "deadline_hit": inline and job_ms > (job.inline_deadline_ms or 0),
    }
    # A Celery worker can exit before the global client's background flush runs, so this event
    # needs a client that is flushed here.
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(job.team.uuid),
            event="query scan analyzed",
            properties=properties,
            groups=groups(job.team.organization, job.team),
        )
