from collections.abc import Callable
from time import perf_counter
from typing import Any, TypeVar

from posthog.schema import CacheMissResponse, HogQLQuery, QueryStatusResponse

from posthog.hogql.constants import LimitContext
from posthog.hogql.query_stats import query_stats_scope

from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team
from posthog.models.user import User

T = TypeVar("T")


class AutoresearchQueryError(Exception):
    pass


@frozen
class QueryContext:
    """The ClickHouse budget a query runs under: its limit context (which sets `max_execution_time`) and workload."""

    limit_context: LimitContext
    workload: Workload


# A query inside a web request keeps the 60 s interactive limit, because a longer query
# would outlive the request.
INTERACTIVE_QUERY = QueryContext(limit_context=LimitContext.QUERY, workload=Workload.DEFAULT)
# Scoring and online validation run in a Temporal activity that nobody waits on, so they
# get the increased batch limit and run on the offline workload.
BATCH_QUERY = QueryContext(limit_context=LimitContext.QUERY_ASYNC, workload=Workload.OFFLINE)


@frozen
class QueryCost:
    """What the ClickHouse queries of one call cost: wall-clock seconds and the rows they read."""

    elapsed_s: float
    rows_read: int


def measure_queries(call: Callable[[], T]) -> tuple[T, QueryCost]:
    """Run ``call`` and return its result with the cost of the ClickHouse queries it ran.

    A scope that is already open (a query runner around this call) collects the same queries,
    so the cost is the difference of its totals across the call.
    """
    start = perf_counter()
    with query_stats_scope() as stats:
        rows_before = stats.rows_read
        result = call()
        rows_read = stats.rows_read - rows_before
    return result, QueryCost(elapsed_s=round(perf_counter() - start, 3), rows_read=rows_read)


@frozen
class HogQLResult:
    columns: list[str]
    rows: list[list[Any]]
    # True when the runner's default paginator cut the result short. A query with no
    # top-level LIMIT is capped at 100 rows, so a caller that materializes rows must
    # either bound the query itself or refuse a truncated result.
    has_more: bool = False

    def as_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row)) for row in self.rows]


def run_hogql(
    *,
    team: Team,
    query: HogQLQuery,
    user: User | None = None,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> HogQLResult:
    """Run a HogQL query under a blocking execution mode and return its columns and rows.

    `user` is the person HogQL applies access control for: the request user on an API
    path, and the pipeline's creator on a background path (scoring, online validation),
    as `posthog/hogql/ACCESS_CONTROL.md` prescribes for jobs that act for a user. With
    no user HogQL fails closed: it denies every warehouse table and applies only the
    default property restrictions, so a pipeline can be masked from data its creator
    may read.

    The runner's return type also covers the cache-miss and async-status shapes that
    a blocking mode never produces. Raising on those keeps every caller off the union,
    and keeps "the query returned nothing" distinct from "the query did not run",
    which callers here read as a real zero.
    """
    response = HogQLQueryRunner(
        query=query,
        team=team,
        user=user,
        limit_context=query_context.limit_context,
        workload=query_context.workload,
    ).run(execution_mode=execution_mode)
    if isinstance(response, CacheMissResponse | QueryStatusResponse):
        raise AutoresearchQueryError(f"HogQL query did not execute: got {type(response).__name__}")
    return HogQLResult(
        columns=[str(c) for c in (response.columns or [])],
        rows=response.results or [],
        has_more=bool(response.hasMore),
    )


def run_hogql_rows(
    *,
    team: Team,
    query: HogQLQuery,
    user: User | None = None,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> list[list[Any]]:
    return run_hogql(team=team, query=query, user=user, execution_mode=execution_mode, query_context=query_context).rows
