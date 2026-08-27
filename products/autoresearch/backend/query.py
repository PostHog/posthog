from typing import Any

from posthog.schema import CacheMissResponse, HogQLQuery, QueryStatusResponse

from posthog.dataclasses import frozen
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team


class AutoresearchQueryError(Exception):
    pass


@frozen
class HogQLResult:
    columns: list[str]
    rows: list[list[Any]]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row)) for row in self.rows]


def run_hogql(
    *,
    team: Team,
    query: HogQLQuery,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
) -> HogQLResult:
    """Run a HogQL query under a blocking execution mode and return its columns and rows.

    The runner's return type also covers the cache-miss and async-status shapes that
    a blocking mode never produces. Raising on those keeps every caller off the union,
    and keeps "the query returned nothing" distinct from "the query did not run",
    which callers here read as a real zero.
    """
    response = HogQLQueryRunner(query=query, team=team).run(execution_mode=execution_mode)
    if isinstance(response, CacheMissResponse | QueryStatusResponse):
        raise AutoresearchQueryError(f"HogQL query did not execute: got {type(response).__name__}")
    return HogQLResult(columns=[str(c) for c in (response.columns or [])], rows=response.results or [])


def run_hogql_rows(
    *,
    team: Team,
    query: HogQLQuery,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
) -> list[list[Any]]:
    return run_hogql(team=team, query=query, execution_mode=execution_mode).rows
