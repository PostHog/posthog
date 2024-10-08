from datetime import datetime
from typing import Optional

from posthog.caching.utils import ThresholdMode, is_stale
from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    CachedTeamTaxonomyQueryResponse,
    TeamTaxonomyQuery,
    TeamTaxonomyQueryResponse,
    TeamTaxonomyResponse,
)


class TeamTaxonomyQueryRunner(QueryRunner):
    """
    Calculates the top events for a team sorted by count. The EventDefinition model doesn't store the count of events,
    so this query mitigates that.
    """

    query: TeamTaxonomyQuery
    response: TeamTaxonomyQueryResponse
    cached_response: CachedTeamTaxonomyQueryResponse

    def calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="TeamTaxonomyQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results: list[TeamTaxonomyResponse] = []
        for event, count in response.results:
            results.append(TeamTaxonomyResponse(event=event, count=count))

        return TeamTaxonomyQueryResponse(
            results=results, timings=response.timings, hogql=hogql, modifiers=self.modifiers
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        query = parse_select(
            """
                SELECT
                    event,
                    count() as count
                FROM events
                WHERE
                    timestamp >= now () - INTERVAL 30 DAY
                GROUP BY
                    event
                ORDER BY
                    count DESC
            """
        )

        return query

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        """
        Despite the lazy mode, it caches for an hour by default. We don't want frequent updates here.
        """
        return is_stale(self.team, date_to=None, interval=None, last_refresh=last_refresh, mode=ThresholdMode.AI)

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        return None
