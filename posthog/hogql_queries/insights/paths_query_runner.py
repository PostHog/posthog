from datetime import datetime, timedelta
from math import ceil
from typing import Any, Dict
from typing import Optional

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.caching.utils import is_stale
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.util import correct_result_for_sampling
from posthog.schema import (
    HogQLQueryModifiers,
    PathsQueryResponse,
)
from posthog.schema import PathsQuery

EVENT_IN_SESSION_LIMIT_DEFAULT = 5
SESSION_TIME_THRESHOLD_DEFAULT_MILLISECONDS = 1800000  # milliseconds to 30 minutes
EDGE_LIMIT_DEFAULT = 50


class PathsQueryRunner(QueryRunner):
    query: PathsQuery
    query_type = PathsQuery

    def __init__(
        self,
        query: PathsQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

    @property
    def group_type_index(self) -> int | None:
        return self.query.aggregation_group_type_index

    def paths_events_query(self) -> ast.SelectQuery:
        event_filters = [
            # event query
        ]

        fields = [
            ast.Field(chain=["events", "timestamp"]),
            ast.Field(chain=["events", "person_id"]),
            ast.Alias(
                alias="path_item_ungrouped",
                expr=ast.Field(chain=["events", "event"]),
            ),
            ast.Alias(
                alias="path_item",
                expr=ast.Field(chain=["events", "event"]),
            ),  # TODO: path cleaning rules
        ]
        # grouping fields
        # event conditional

        if self.query.properties is not None and self.query.properties != []:
            event_filters.append(property_to_expr(self.query.properties, self.team))

        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for prop in self.team.test_account_filters:
                event_filters.append(property_to_expr(prop, self.team))

        date_filter_expr = self.date_filter_expr()
        event_filters.append(date_filter_expr)

        result = ast.SelectQuery(
            select=fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=event_filters),
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["person_id"])),
                ast.OrderExpr(expr=ast.Field(chain=["timestamp"])),
            ],
        )

        if self.query.samplingFactor is not None and isinstance(self.query.samplingFactor, float):
            result.select_from.sample = ast.SampleExpr(
                sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))
            )

        return result

    def date_filter_expr(self) -> ast.Expr:
        field_to_compare = ast.Field(chain=["events", "timestamp"])
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=field_to_compare,
                    right=ast.Constant(value=self.query_date_range.date_from()),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=field_to_compare,
                    right=ast.Constant(value=self.query_date_range.date_to()),
                ),
            ]
        )

    def actor_query(self) -> ast.SelectQuery:
        target_point = self.query.pathsFilter.end_point or self.query.pathsFilter.start_point

        placeholders = {
            "path_event_query": self.paths_events_query(),
            "boundary_event_filter": ast.Constant(value=None),
            "target_point": ast.Constant(value=target_point),
            "target_clause": ast.Constant(value=None),
            "session_threshold_clause": ast.Constant(value=None),
            "session_time_threshold": ast.Constant(value=SESSION_TIME_THRESHOLD_DEFAULT_MILLISECONDS),
            # TODO: "extra_final_select_statements": ast.Constant(value=None),
            "extra_joined_path_tuple_select_statements": ast.Constant(value=None),
            "extra_array_filter_select_statements": ast.Constant(value=None),
            "extra_limited_path_tuple_elements": ast.Constant(value=None),
            "extra_path_time_tuple_select_statements": ast.Constant(value=None),
            "extra_paths_tuple_elements": ast.Constant(value=None),
            "extra_group_array_select_statements": ast.Constant(value=None),
        }
        return parse_select(
            """
                SELECT
                    person_id,
                    path,
                    conversion_time,
                    event_in_session_index,
                    concat(toString(event_in_session_index), '_', path) as path_key,
                    if(event_in_session_index > 1, concat(toString(event_in_session_index-1), '_', prev_path), null) AS last_path_key,
                    path_dropoff_key
                FROM (
                    SELECT
                        person_id,
                        joined_path_tuple.1 as path,
                        joined_path_tuple.2 as conversion_time,
                        joined_path_tuple.3 as prev_path,
                        event_in_session_index,
                        session_index,
                        arrayPopFront(arrayPushBack(path_basic, '')) as path_basic_0,
                        arrayMap((x,y) -> if(x=y, 0, 1), path_basic, path_basic_0) as mapping,
                        arrayFilter((x,y) -> y, time, mapping) as timings,
                        arrayFilter((x,y)->y, path_basic, mapping) as compact_path,
                        indexOf(compact_path, {target_point}) as target_index,
                        arrayDifference(limited_timings) as timings_diff,
                        arrayZip(limited_path, timings_diff, arrayPopBack(arrayPushFront(limited_path, ''))) as limited_path_timings,
                        concat(toString(length(limited_path)), '_', limited_path[-1]) as path_dropoff_key /* last path item */
                    FROM (
                        SELECT
                            person_id,
                            path_time_tuple.1 as path_basic,
                            path_time_tuple.2 as time,
                            session_index,
                            arrayZip(paths, timing, arrayDifference(timing)) as paths_tuple,
                            arraySplit(x -> if(x.3 < {session_time_threshold}, 0, 1), paths_tuple) as session_paths
                        FROM (
                            SELECT
                                person_id,
                                groupArray(toUnixTimestamp64Milli(timestamp)) as timing,
                                groupArray(path_item) as paths
                            FROM {path_event_query}
                            GROUP BY person_id
                        )
                        /* this array join splits paths for a single personID per session */
                        ARRAY JOIN
                            session_paths AS path_time_tuple,
                            arrayEnumerate(session_paths) AS session_index
                    )
                    ARRAY JOIN
                        limited_path_timings AS joined_path_tuple,
                        arrayEnumerate(limited_path_timings) AS event_in_session_index
                )
            """,
            placeholders,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        # TODO: Weight filter
        # TODO: Edge limit

        placeholders = {
            "paths_per_person_query": self.actor_query(),
        }
        with self.timings.measure("paths_query"):
            paths_query = parse_select(
                """
                    SELECT
                        last_path_key as source_event,
                        path_key as target_event,
                        COUNT(*) AS event_count,
                        avg(conversion_time) AS average_conversion_time
                    FROM {paths_per_person_query}
                    WHERE source_event IS NOT NULL
                    GROUP BY source_event,
                            target_event
                    ORDER BY event_count DESC,
                            source_event,
                            target_event
                """,
                placeholders,
                timings=self.timings,
            )
        return paths_query

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            now=datetime.now(),
        )

    def _is_stale(self, cached_result_package):
        date_to = self.query_date_range.date_to()
        interval = self.query_date_range.interval_name
        return is_stale(self.team, date_to, interval, cached_result_package)

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency

    def calculate(self) -> PathsQueryResponse:
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="PathsQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        # TODO: Validate results?

        results = (
            {
                "source": source,
                "target": target,
                "value": correct_result_for_sampling(value, self.query.samplingFactor),
                "average_conversion_time": avg_conversion_time,
            }
            for source, target, value, avg_conversion_time in response.results
        )

        return PathsQueryResponse(results=results, timings=response.timings, hogql=hogql)

    def to_actors_query(self, interval: Optional[int] = None) -> ast.SelectQuery:
        with self.timings.measure("paths_query"):
            paths_query = parse_select(
                """
                    SELECT
                        actor_id,
                        groupArray(actor_activity.intervals_from_base) AS appearance_intervals,
                        arraySort(appearance_intervals) AS appearances

                    FROM {actor_query} AS actor_activity

                    GROUP BY actor_id
                """,
                placeholders={
                    "actor_query": self.actor_query(),
                },
                timings=self.timings,
            )
            # We want to expose each interval as a separate column
            for i in range(self.query_date_range.total_intervals - interval):
                paths_query.select.append(
                    ast.Alias(
                        alias=f"{self.query_date_range.interval_name}_{i}",
                        expr=ast.Call(
                            name="arrayExists",
                            args=[
                                ast.Lambda(
                                    args=["x"],
                                    expr=ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["x"]),
                                        right=ast.Constant(value=i),
                                    ),
                                ),
                                ast.Field(chain=["appearance_intervals"]),
                            ],
                        ),
                    )
                )
        return paths_query
