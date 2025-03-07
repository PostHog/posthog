from datetime import datetime
from functools import cached_property

from typing import Any
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr, parse_select
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

POSTHOG_OTHER = "$$_posthog_other_$$"
POSTHOG_DROPOFF = "$$_posthog_dropoff_$$"


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
        self.collapse_events: bool = (
            self.query.pathsV2Filter.collapseEvents or PathsV2Filter.model_fields["collapseEvents"].default
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
            PathsV2Item(step_index=step_index, source_step=source, target_step=target, value=value)
            for step_index, source, target, value in response.results
            if source is not None
        ]

        return PathsV2QueryResponse(
            results=results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
        )

    def _event_base_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        - Applies property and date filters.
        - Extracts "path items" i.e. strings representing the current step in the sequence of events.

        Example:
        ┌──────────────────timestamp─┬─actor_id─────────────────────────────┬─path_item────┐
        │ 2023-03-11 11:30:00.000000 │ 631e1988-3971-79a2-02ae-b09da769be2e │ Landing Page │
        │ 2023-03-11 11:32:00.000000 │ 631e1988-3971-79a2-02ae-b09da769be2e │ Search       │
        │ 2023-03-11 11:35:00.000000 │ 631e1988-3971-79a2-02ae-b09da769be2e │ Product View │
        │ 2023-03-11 11:38:00.000000 │ 631e1988-3971-79a2-02ae-b09da769be2e │ Add to Cart  │
        │ 2023-03-11 11:42:00.000000 │ 631e1988-3971-79a2-02ae-b09da769be2e │ Checkout     │
        │ 2023-03-11 11:45:00.000000 │ 631e1988-3971-79a2-02ae-b09da769be2e │ Purchase     │
        │ 2023-03-12 10:00:00.000000 │ 30b444d4-6fb7-8f08-67f1-3f70d30c5746 │ Landing Page │
        │ 2023-03-12 10:02:00.000000 │ 30b444d4-6fb7-8f08-67f1-3f70d30c5746 │ Product View │
        │ 2023-03-12 10:05:00.000000 │ 30b444d4-6fb7-8f08-67f1-3f70d30c5746 │ Add to Cart  │
        │ 2023-03-13 09:00:00.000000 │ 6c012bb7-f3f6-5f0f-f72a-473ee658fdec │ Landing Page │
        │ 2023-03-10 12:00:00.000000 │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │ Landing Page │
        │ 2023-03-10 12:05:00.000000 │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │ Product View │
        │ 2023-03-10 12:10:00.000000 │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │ Add to Cart  │
        │ 2023-03-10 12:15:00.000000 │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │ Checkout     │
        │ 2023-03-10 12:20:00.000000 │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │ Purchase     │
        └────────────────────────────┴──────────────────────────────────────┴──────────────┘
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
        ┌─actor_id─────────────────────────────┬─timestamp_array─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬─path_item_array──────────────────────────────────────────────────────────────┐
        │ 6c012bb7-f3f6-5f0f-f72a-473ee658fdec │ ['2023-03-13 09:00:00.000000']                                                                                                                                                  │ ['Landing Page']                                                             │
        │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │ ['2023-03-10 12:00:00.000000','2023-03-10 12:05:00.000000','2023-03-10 12:10:00.000000','2023-03-10 12:15:00.000000','2023-03-10 12:20:00.000000']                              │ ['Landing Page','Product View','Add to Cart','Checkout','Purchase']          │
        │ 30b444d4-6fb7-8f08-67f1-3f70d30c5746 │ ['2023-03-12 10:00:00.000000','2023-03-12 10:02:00.000000','2023-03-12 10:05:00.000000']                                                                                        │ ['Landing Page','Product View','Add to Cart']                                │
        │ 631e1988-3971-79a2-02ae-b09da769be2e │ ['2023-03-11 11:30:00.000000','2023-03-11 11:32:00.000000','2023-03-11 11:35:00.000000','2023-03-11 11:38:00.000000','2023-03-11 11:42:00.000000','2023-03-11 11:45:00.000000'] │ ['Landing Page','Search','Product View','Add to Cart','Checkout','Purchase'] │
        └──────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────┘
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
        ┌─actor_id─────────────────────────────┬─session_index─┬─paths_array────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬─paths_array_session_split──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬─limited_paths_array_per_session────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
        │ 6c012bb7-f3f6-5f0f-f72a-473ee658fdec │             1 │ [('2023-03-13 09:00:00.000000','Landing Page',NULL)]                                                                                                                                                                                                       │ [[('2023-03-13 09:00:00.000000','Landing Page',NULL)]]                                                                                                                                                                                                     │ [('2023-03-13 09:00:00.000000','Landing Page',NULL)]                                                                                                                                                                                                       │
        │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │             1 │ [('2023-03-10 12:00:00.000000','Landing Page',NULL),('2023-03-10 12:05:00.000000','Product View','2023-03-10 12:00:00.000000'),('2023-03-10 12:10:00.000000','Add to Cart','2023-03-10 12:05:00.000000'),('2023-03-10 12:15:00.000000','Checkout','2023-03-10 12:10:00.000000'),('2023-03-10 12:20:00.000000','Purchase','2023-03-10 12:15:00.000000')] │ [[('2023-03-10 12:00:00.000000','Landing Page',NULL),('2023-03-10 12:05:00.000000','Product View','2023-03-10 12:00:00.000000'),('2023-03-10 12:10:00.000000','Add to Cart','2023-03-10 12:05:00.000000'),('2023-03-10 12:15:00.000000','Checkout','2023-03-10 12:10:00.000000'),('2023-03-10 12:20:00.000000','Purchase','2023-03-10 12:15:00.000000')]] │ [('2023-03-10 12:00:00.000000','Landing Page',NULL),('2023-03-10 12:05:00.000000','Product View','2023-03-10 12:00:00.000000'),('2023-03-10 12:10:00.000000','Add to Cart','2023-03-10 12:05:00.000000'),('2023-03-10 12:15:00.000000','Checkout','2023-03-10 12:10:00.000000')] │
        │ 30b444d4-6fb7-8f08-67f1-3f70d30c5746 │             1 │ [('2023-03-12 10:00:00.000000','Landing Page',NULL),('2023-03-12 10:02:00.000000','Product View','2023-03-12 10:00:00.000000'),('2023-03-12 10:05:00.000000','Add to Cart','2023-03-12 10:02:00.000000')]                                                  │ [[('2023-03-12 10:00:00.000000','Landing Page',NULL),('2023-03-12 10:02:00.000000','Product View','2023-03-12 10:00:00.000000'),('2023-03-12 10:05:00.000000','Add to Cart','2023-03-12 10:02:00.000000')]]                                                │ [('2023-03-12 10:00:00.000000','Landing Page',NULL),('2023-03-12 10:02:00.000000','Product View','2023-03-12 10:00:00.000000'),('2023-03-12 10:05:00.000000','Add to Cart','2023-03-12 10:02:00.000000')]                                                  │
        │ 631e1988-3971-79a2-02ae-b09da769be2e │             1 │ [('2023-03-11 11:30:00.000000','Landing Page',NULL),('2023-03-11 11:32:00.000000','Search','2023-03-11 11:30:00.000000'),('2023-03-11 11:35:00.000000','Product View','2023-03-11 11:32:00.000000'),('2023-03-11 11:38:00.000000','Add to Cart','2023-03-11 11:35:00.000000'),('2023-03-11 11:42:00.000000','Checkout','2023-03-11 11:38:00.000000'),('2023-03-11 11:45:00.000000','Purchase','2023-03-11 11:42:00.000000')] │ [[('2023-03-11 11:30:00.000000','Landing Page',NULL),('2023-03-11 11:32:00.000000','Search','2023-03-11 11:30:00.000000'),('2023-03-11 11:35:00.000000','Product View','2023-03-11 11:32:00.000000'),('2023-03-11 11:38:00.000000','Add to Cart','2023-03-11 11:35:00.000000'),('2023-03-11 11:42:00.000000','Checkout','2023-03-11 11:38:00.000000'),('2023-03-11 11:45:00.000000','Purchase','2023-03-11 11:42:00.000000')]] │ [('2023-03-11 11:30:00.000000','Landing Page',NULL),('2023-03-11 11:32:00.000000','Search','2023-03-11 11:30:00.000000'),('2023-03-11 11:35:00.000000','Product View','2023-03-11 11:32:00.000000'),('2023-03-11 11:38:00.000000','Add to Cart','2023-03-11 11:35:00.000000')] │
        └──────────────────────────────────────┴───────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
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

                /* Adds dropoffs. */
                arrayPushBack(paths_array_per_session, (now(), {POSTHOG_DROPOFF}, now())) as paths_array_per_session_with_dropoffs,

                /* Returns the first n events per session. */
                arraySlice(paths_array_per_session_with_dropoffs, 1, {max_steps}) as limited_paths_array_per_session
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

        Example:
        ┌─actor_id─────────────────────────────┬─session_index─┬─step_in_session_index─┬──────────────────timestamp─┬─path_item────┬─previous_path_item─┐
        │ 6c012bb7-f3f6-5f0f-f72a-473ee658fdec │             1 │                     1 │ 2023-03-13 09:00:00.000000 │ Landing Page │ ᴺᵁᴸᴸ               │
        │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │             1 │                     1 │ 2023-03-10 12:00:00.000000 │ Landing Page │ ᴺᵁᴸᴸ               │
        │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │             1 │                     2 │ 2023-03-10 12:05:00.000000 │ Product View │ Landing Page       │
        │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │             1 │                     3 │ 2023-03-10 12:10:00.000000 │ Add to Cart  │ Product View       │
        │ be012a47-61e6-43d7-fa0a-8f0a1d229610 │             1 │                     4 │ 2023-03-10 12:15:00.000000 │ Checkout     │ Add to Cart        │
        │ 30b444d4-6fb7-8f08-67f1-3f70d30c5746 │             1 │                     1 │ 2023-03-12 10:00:00.000000 │ Landing Page │ ᴺᵁᴸᴸ               │
        │ 30b444d4-6fb7-8f08-67f1-3f70d30c5746 │             1 │                     2 │ 2023-03-12 10:02:00.000000 │ Product View │ Landing Page       │
        │ 30b444d4-6fb7-8f08-67f1-3f70d30c5746 │             1 │                     3 │ 2023-03-12 10:05:00.000000 │ Add to Cart  │ Product View       │
        │ 631e1988-3971-79a2-02ae-b09da769be2e │             1 │                     1 │ 2023-03-11 11:30:00.000000 │ Landing Page │ ᴺᵁᴸᴸ               │
        │ 631e1988-3971-79a2-02ae-b09da769be2e │             1 │                     2 │ 2023-03-11 11:32:00.000000 │ Search       │ Landing Page       │
        │ 631e1988-3971-79a2-02ae-b09da769be2e │             1 │                     3 │ 2023-03-11 11:35:00.000000 │ Product View │ Search             │
        │ 631e1988-3971-79a2-02ae-b09da769be2e │             1 │                     4 │ 2023-03-11 11:38:00.000000 │ Add to Cart  │ Product View       │
        └──────────────────────────────────────┴───────────────┴───────────────────────┴────────────────────────────┴──────────────┴────────────────────┘
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
            WHERE {collapse_events_filter}
        """,
            placeholders={
                "paths_per_actor_and_session_as_tuple_query": self._paths_per_actor_and_session_as_tuple_query(),
                "collapse_events_filter": (
                    parse_expr("path_item != previous_path_item") if self.collapse_events else parse_expr("1=1")
                ),
            },
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        - Groups the individual paths and orders them by frequency.

        Example:
        ┌─event_count─┬─step_index─┬─row_number─┬─source_step──┬─target_step──┐
        │           2 │          2 │          1 │ Landing Page │ Product View │
        │           1 │          2 │          2 │ Landing Page │ Search       │
        │           2 │          3 │          1 │ Product View │ Add to Cart  │
        │           1 │          3 │          2 │ Search       │ Product View │
        │           1 │          4 │          2 │ Add to Cart  │ Checkout    │
        │           1 │          4 │          1 │ Product View │ Add to Cart │
        └─────────────┴────────────┴────────────┴──────────────┴─────────────┘
        """
        return parse_select(
            """
            WITH
                path_links AS (
                    SELECT
                        step_in_session_index as step_index,
                        COUNT(*) AS value,
                        previous_path_item as source_step,
                        path_item AS target_step
                    FROM {paths_flattened_with_previous_item}
                    GROUP BY step_index,
                        previous_path_item,
                        path_item
                ),
                source_steps_to_keep AS (
                    SELECT step_index, source_step
                    FROM (
                        SELECT
                            step_index,
                            source_step,
                            SUM(value) AS total_value,
                            ROW_NUMBER() OVER (PARTITION BY step_index ORDER BY SUM(value) DESC) AS rn
                        FROM path_links
                        WHERE source_step != {POSTHOG_DROPOFF}
                        GROUP BY step_index, source_step
                    )
                    WHERE rn <= {max_rows_per_step}
                )
            SELECT
                path_links.step_index,
                CASE WHEN path_links.source_step = {POSTHOG_DROPOFF} OR ts.source_step IS NOT NULL THEN path_links.source_step ELSE {POSTHOG_OTHER} END AS source_step,
                target_step,
                SUM(path_links.value) AS total_value
            FROM path_links
            LEFT JOIN source_steps_to_keep ts ON path_links.step_index = ts.step_index AND path_links.source_step = ts.source_step
            GROUP BY
                path_links.step_index,
                CASE WHEN path_links.source_step = {POSTHOG_DROPOFF} OR ts.source_step IS NOT NULL THEN path_links.source_step ELSE {POSTHOG_OTHER} END,
                target_step
            ORDER BY path_links.step_index ASC, total_value DESC
            """,
            placeholders={
                "paths_flattened_with_previous_item": self._paths_flattened_with_previous_item(),
                "max_rows_per_step": ast.Constant(value=self.max_rows_per_step),
                "POSTHOG_OTHER": ast.Constant(value=POSTHOG_OTHER),
                "POSTHOG_DROPOFF": ast.Constant(value=POSTHOG_DROPOFF),
            },
        )
