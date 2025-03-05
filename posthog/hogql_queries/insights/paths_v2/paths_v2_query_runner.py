from datetime import datetime
from functools import cached_property

from typing import Any
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.paths_v2.utils import interval_unit_to_sql
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team
from posthog.schema import (
    CachedPathsV2QueryResponse,
    ConversionWindowIntervalUnit,
    HogQLQueryModifiers,
    PathsV2Filter,
    PathsV2Item,
    PathsV2Query,
    PathsV2QueryResponse,
)


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

        if not self.query.pathsV2Filter:
            self.query.pathsV2Filter = PathsV2Filter()

        self.max_steps: int = self.query.pathsV2Filter.maxSteps or PathsV2Filter.model_fields["maxSteps"].default
        self.max_rows_per_step: int = (
            self.query.pathsV2Filter.maxRowsPerStep or PathsV2Filter.model_fields["maxRowsPerStep"].default
        )
        self.interval: int = (
            self.query.pathsV2Filter.windowInterval or PathsV2Filter.model_fields["windowInterval"].default
        )
        self.interval_unit: ConversionWindowIntervalUnit = (
            self.query.pathsV2Filter.windowIntervalUnit or PathsV2Filter.model_fields["windowIntervalUnit"].default
        )

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def calculate(self) -> PathsV2QueryResponse:
        response = execute_hogql_query(
            query_type="PathsV2Query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results = [
            PathsV2Item(step_index=step_index, source_step=source, target_step=target, event_count=count)
            for step_index, source, count, _row_number, target in response.results
        ]

        return PathsV2QueryResponse(
            results=results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
        )

    def _event_base_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        - Applies property and date filters.
        - Extracts "path items" i.e. strings representing the current step in the sequence of events.

        Example:
        timestamp            actor_id                              path_item
        -------------------  ------------------------------------  ----------
        2025-02-20T20:57:55  018dd1b5-b644-0000-0000-20b757aa605e  some event
        2025-02-21T20:46:27  018dd1b5-b644-0000-0000-20b757aa605e  some event
        """

        # date range filter
        event_filters: list[ast.CompareOperation | ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=self.query_date_range.date_from_to_start_of_interval_hogql(),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=self.query_date_range.date_to_as_hogql(),
            ),
        ]

        # properties filter
        if self.query.properties is not None and self.query.properties != []:
            event_filters.append(property_to_expr(self.query.properties, self.team))

        # test account filter
        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for prop in self.team.test_account_filters:
                event_filters.append(property_to_expr(prop, self.team))

        return parse_select(
            """
            SELECT
                timestamp,
                person_id as actor_id,
                event as path_item
            FROM events
            WHERE {filters}
            ORDER BY actor_id, timestamp
        """,
            placeholders={"filters": ast.And(exprs=event_filters)},
        )

    def _paths_per_actor_as_array_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        - Aggregates the timestamps and path items for each actor into arrays.

        Example:
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
                "event_base_query": self._event_base_query(),
            },
        )

    def _paths_per_actor_and_session_as_tuple_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        - Combines the timestamp and path item arrays into an array of tuples, including the previous step's timestamp.
        - Compares the two timestamps with the session interval to split the array into sessions.
        - Keeps only the first `max_steps` steps of each session.
        - Flattens the sessions, annotated by a session index.

        Example:
        """
        return parse_select(
            """
            SELECT actor_id,
                session_index,

                /* Combines the two arrays into an array of tuples, where each tuple contains:
                1. The timestamp.
                2. The path item.
                3. The previous step's timestamp. */
                arrayZip(
                    timestamp_array,
                    path_item_array,
                    arrayPopBack(arrayPushFront(timestamp_array, NULL))
                ) as paths_array,

                /* Splits the tuple array if the difference between the current and the
                previous timestamp is greater than the session window. */
                arraySplit(x->if(x.1 < x.3 + {session_interval}, 0, 1), paths_array) as paths_array_session_split,

                /* Returns the first n events per session. */
                arraySlice(paths_array_per_session, 1, {max_steps}) as limited_paths_array_per_session
            FROM {paths_per_actor_as_array_query}
            ARRAY JOIN paths_array_session_split AS paths_array_per_session,
                arrayEnumerate(paths_array_session_split) AS session_index
        """,
            placeholders={
                "paths_per_actor_as_array_query": self._paths_per_actor_as_array_query(),
                "max_steps": ast.Constant(value=self.max_steps),
                "session_interval": ast.Call(
                    name=interval_unit_to_sql(self.interval_unit),
                    args=[ast.Constant(value=self.interval)],
                ),
            },
        )

    def _paths_flattened_with_previous_item(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        - Adds the previous path item to the output.
        - Flattens the sequence of events (i.e. timestamp/path item tuples) in a session.
        """
        return parse_select(
            """
            SELECT actor_id,
                session_index,
                step_in_session_index,
                path_tuple.1 AS timestamp,
                path_tuple.2 AS path_item,

                /* Add the previous path item. */
                if(step_in_session_index = 1,
                    null,
                    arrayElement(limited_paths_array_per_session, step_in_session_index - 1).2
                ) AS previous_path_item
            FROM {paths_per_actor_and_session_as_tuple_query}
            ARRAY JOIN limited_paths_array_per_session AS path_tuple,
                arrayEnumerate(limited_paths_array_per_session) AS step_in_session_index
        """,
            placeholders={
                "paths_per_actor_and_session_as_tuple_query": self._paths_per_actor_and_session_as_tuple_query(),
            },
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        - Groups the individual paths and orders them by frequency.
        """
        return parse_select(
            """
            SELECT
                step_in_session_index as step_index,
                previous_path_item as source_step,
                COUNT(*) AS event_count,
                row_number() OVER (PARTITION BY step_index ORDER BY event_count DESC) AS row_number,
                if(row_number <= {max_rows_per_step}, path_item, '$$_posthog_breakdown_other_$$') AS target_step
            FROM {paths_flattened_with_previous_item}
            WHERE source_step IS NOT NULL
            GROUP BY step_index,
                source_step,
                path_item
            ORDER BY step_index ASC,
                event_count DESC,
                source_step,
                target_step
        """,
            placeholders={
                "paths_flattened_with_previous_item": self._paths_flattened_with_previous_item(),
                "max_rows_per_step": ast.Constant(value=self.max_rows_per_step),
            },
        )
