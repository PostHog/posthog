from typing import Any
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models.team.team import Team
from posthog.schema import CachedPathsV2QueryResponse, HogQLQueryModifiers, PathsV2Query, PathsV2QueryResponse


class PathsV2QueryRunner(QueryRunner):
    query: PathsV2Query
    response: PathsV2QueryResponse
    cached_response: CachedPathsV2QueryResponse

    def __init__(
        self,
        query: PathsV2Query | dict[str, Any],
        team: Team,
        timings: HogQLTimings | None = None,
        modifiers: HogQLQueryModifiers | None = None,
        limit_context: LimitContext | None = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

    def calculate(self) -> PathsV2QueryResponse:
        response = execute_hogql_query(
            query_type="PathsV2Query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        return PathsV2QueryResponse(
            results=response.results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select("select 1 limit 0")
