from datetime import datetime, timedelta
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.schema import (
    CachedReplayActiveScreensQueryResponse,
    ReplayActiveScreensQuery,
    ReplayActiveScreensQueryResponse,
)


class ReplayActiveScreensQueryRunner(AnalyticsQueryRunner[ReplayActiveScreensQueryResponse]):
    query: ReplayActiveScreensQuery
    cached_response: CachedReplayActiveScreensQueryResponse

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + timedelta(hours=1)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # Use Python's datetime.now() which respects frozen time in tests
        now = datetime.now()

        query = """
            SELECT
                cutQueryString(cutFragment(url)) as screen,
                count(distinct session_id) as count
            FROM (
                SELECT
                    session_id,
                    arrayJoin(any(all_urls)) as url
                FROM raw_session_replay_events
                WHERE min_first_timestamp >= {python_now} - interval 7 day
                  AND min_first_timestamp <= {python_now}
                GROUP BY session_id
                HAVING date_diff('second', min(min_first_timestamp), max(max_last_timestamp)) > 5
            )
            GROUP BY screen
            ORDER BY count DESC
            LIMIT 10
        """

        with self.timings.measure("parse_select"):
            parsed_select = parse_select(
                query, placeholders={"python_now": ast.Constant(value=now)}, timings=self.timings
            )

        return parsed_select

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self.to_query()

    def _calculate(self) -> ReplayActiveScreensQueryResponse:
        query = self.to_query()

        response = execute_hogql_query(
            query_type="ReplayActiveScreensQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.query.modifiers or self.modifiers,
            limit_context=self.limit_context,
            workload=self.workload,
        )

        results = []
        for row in response.results or []:
            results.append(
                {
                    "screen": str(row[0]),
                    "count": row[1],
                }
            )

        return ReplayActiveScreensQueryResponse(
            results=results,
            timings=response.timings,
            types=response.types,
            columns=response.columns,
            hasMore=response.hasMore,
            limit=response.limit,
            offset=response.offset,
            hogql=response.hogql,
        )
