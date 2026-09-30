from typing import Any

from posthog.schema import CacheMissResponse, HogQLQuery, QueryStatusResponse

from posthog.dataclasses import frozen
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team
from posthog.models.user import User


class AutoresearchQueryError(Exception):
    pass


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
    response = HogQLQueryRunner(query=query, team=team, user=user).run(execution_mode=execution_mode)
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
) -> list[list[Any]]:
    return run_hogql(team=team, query=query, user=user, execution_mode=execution_mode).rows
