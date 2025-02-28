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

    def event_base_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        timestamp            actor_id                              path_item
        -------------------  ------------------------------------  ----------
        2025-02-20T20:57:55  018dd1b5-b644-0000-0000-20b757aa605e  some event
        2025-02-21T20:46:27  018dd1b5-b644-0000-0000-20b757aa605e  some event
        """
        return parse_select(
            """
            SELECT
                timestamp,
                person_id as actor_id,
                event as path_item
            FROM events
            WHERE 1=1
            ORDER BY actor_id, timestamp
        """
        )

    def paths_per_actor_as_array_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        actor_id                              timestamp_array                                 path_item_array
        ------------------------------------  ----------------------------------------------  ----------------------------
        018dd1b5-b644-0000-0000-20b757aa605e  ['2025-02-20T20:57:55', '2025-02-21T20:46:27']  ['some event', 'some event']
        """
        return parse_select(
            """
            SELECT
                actor_id,
                groupArray(timestamp) as timestamp_array,
                groupArray(path_item) as path_item_array
            FROM {event_base_query}
            GROUP BY actor_id
        """,
            placeholders={
                "event_base_query": self.event_base_query(),
            },
        )

    def paths_per_actor_and_session_as_tuple_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                actor_id,
                --path_time_tuple.1 as path_basic,
                --path_time_tuple.2 as time,
                session_index,

                /* Combines the two arrays into an array of tuples, where each tuple contains:
                1. The timestamp.
                2. The path item.
                3. The time difference between the current and previous timestamp. */
                arrayZip(timestamp_array, path_item_array, arrayDifference(timestamp_array)) as paths_array,

                /* Splits the tuple array if the time difference is greater than the session window. */
                arraySplit(x -> if(x.3 < (1800), 0, 1), paths_array) as paths_array_session_split
            FROM {paths_per_actor_as_array_query}
            ARRAY JOIN
                paths_array_session_split AS paths_array_per_session,
                arrayEnumerate(paths_array_per_session) AS session_index
        """,
            placeholders={
                "paths_per_actor_as_array_query": self.paths_per_actor_as_array_query(),
            },
        )
