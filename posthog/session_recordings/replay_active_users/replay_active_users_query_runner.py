from datetime import datetime, timedelta
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.schema import (
    CachedReplayActiveUsersQueryResponse,
    ReplayActiveUsersQuery,
    ReplayActiveUsersQueryResponse,
)


class ReplayActiveUsersQueryRunner(AnalyticsQueryRunner[ReplayActiveUsersQueryResponse]):
    query: ReplayActiveUsersQuery
    cached_response: CachedReplayActiveUsersQueryResponse

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None

        return last_refresh + timedelta(hours=1)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # Use Python's datetime.now() which respects frozen time in tests
        now = datetime.now()

        query = """
            WITH
            counted_sessions AS (
                SELECT
                    session_id,
                    any(distinct_id) AS sess_di,
                    count() AS c
                FROM raw_session_replay_events
                WHERE min_first_timestamp >= {python_now} - interval 7 day
                  AND min_first_timestamp <= {python_now}
                GROUP BY session_id
                HAVING date_diff('second', min(min_first_timestamp), max(max_last_timestamp)) > 5
            ),

            session_persons AS (
                SELECT
                    $session_id as session_id,
                    any(person_id) as person_id,
                    any(person.properties) as pp
                FROM events
                WHERE timestamp >= {python_now} - interval 7 day
                  AND timestamp <= {python_now}
                  AND $session_id IN (SELECT session_id FROM counted_sessions)
                  AND event IN ('$pageview', '$screen', '$autocapture', '$feature_flag_called', '$pageleave', '$identify', '$web_vitals', '$set', 'Application Opened', 'Application Backgrounded')
                GROUP BY $session_id
            )

            SELECT
                sp.person_id,
                sp.pp,
                sum(cs.c) as total_count
            FROM counted_sessions cs
            INNER JOIN session_persons sp ON cs.session_id = sp.session_id
            WHERE sp.person_id IS NOT NULL
            GROUP BY sp.person_id, sp.pp
            ORDER BY total_count DESC
            LIMIT 10
        """

        with self.timings.measure("parse_select"):
            parsed_select = parse_select(
                query, placeholders={"python_now": ast.Constant(value=now)}, timings=self.timings
            )

        return parsed_select

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self.to_query()

    def _calculate(self) -> ReplayActiveUsersQueryResponse:
        query = self.to_query()

        response = execute_hogql_query(
            query_type="ReplayActiveUsersQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.query.modifiers or self.modifiers,
            limit_context=self.limit_context,
            workload=self.workload,
        )

        results = []
        for row in response.results or []:
            # Handle properties - could be JSON string or dict
            properties = row[1]
            if isinstance(properties, str):
                import json

                try:
                    properties = json.loads(properties)
                except (json.JSONDecodeError, TypeError):
                    properties = {}
            elif not isinstance(properties, dict):
                properties = {}

            results.append(
                {
                    "person": {
                        "id": str(row[0]),  # Convert UUID to string
                        "properties": properties,
                    },
                    "count": row[2],  # total_count from the query
                }
            )

        return ReplayActiveUsersQueryResponse(
            results=results,
            timings=response.timings,
            types=response.types,
            columns=response.columns,
            hasMore=response.hasMore,
            limit=response.limit,
            offset=response.offset,
            hogql=response.hogql,
        )
