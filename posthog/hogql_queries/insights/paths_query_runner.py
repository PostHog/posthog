import itertools
from collections import defaultdict
from datetime import datetime, timedelta
from math import ceil
from re import escape
from typing import Any, Literal, Optional, cast

from posthog.schema import (
    CachedPathsQueryResponse,
    FunnelConversionWindowTimeUnit,
    FunnelPathType,
    FunnelsActorsQuery,
    FunnelsFilter,
    HogQLQueryModifiers,
    PathCleaningFilter,
    PathsFilter,
    PathsQuery,
    PathsQueryResponse,
    PathType,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY, HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.constants import HOGQL, PAGEVIEW_EVENT, SCREEN_EVENT
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.utils import funnel_window_interval_unit_to_sql
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.util import correct_result_for_sampling

EVENT_IN_SESSION_LIMIT_DEFAULT = 5
SESSION_TIME_THRESHOLD_DEFAULT_SECONDS = 30 * 60  # 30 minutes
EDGE_LIMIT_DEFAULT = 50


class PathsQueryRunner(AnalyticsQueryRunner[PathsQueryResponse]):
    query: PathsQuery
    cached_response: CachedPathsQueryResponse

    def __init__(
        self,
        query: PathsQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

        if not self.query.pathsFilter:
            self.query.pathsFilter = PathsFilter()

        self.event_in_session_limit = self.query.pathsFilter.stepLimit or EVENT_IN_SESSION_LIMIT_DEFAULT

        self.regex_groupings: list[str] = []
        if self.query.pathsFilter.pathGroupings:
            self.regex_groupings = [
                escape(grouping).replace("\\*", ".*") for grouping in self.query.pathsFilter.pathGroupings
            ]

        self.extra_event_fields: list[str] = []
        self.extra_event_properties: list[str] = []

    @property
    def group_type_index(self) -> int | None:
        return self.query.aggregation_group_type_index

    def _get_event_query(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []
        or_conditions: list[ast.Expr] = []

        if not self.query.pathsFilter.includeEventTypes:
            return []

        if PathType.FIELD_PAGEVIEW in self.query.pathsFilter.includeEventTypes:
            or_conditions.append(parse_expr("event = {event}", {"event": ast.Constant(value=PAGEVIEW_EVENT)}))

        if PathType.FIELD_SCREEN in self.query.pathsFilter.includeEventTypes:
            or_conditions.append(parse_expr("event = {event}", {"event": ast.Constant(value=SCREEN_EVENT)}))

        if PathType.CUSTOM_EVENT in self.query.pathsFilter.includeEventTypes:
            or_conditions.append(parse_expr("NOT startsWith(events.event, '$')"))

        if or_conditions:
            conditions.append(ast.Or(exprs=or_conditions))

        if self.query.pathsFilter.excludeEvents:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotIn,
                    left=ast.Field(chain=["path_item"]),
                    right=ast.Constant(value=self.query.pathsFilter.excludeEvents),
                )
            )

        if conditions:
            return [ast.And(exprs=conditions)]

        return []

    def _should_query_event(self, event: str) -> bool:
        if not self.query.pathsFilter.includeEventTypes:
            return event not in (self.query.pathsFilter.excludeEvents or [])

        return event in (self.query.pathsFilter.includeEventTypes or [])

    def construct_event_hogql(self) -> ast.Expr:
        event_hogql: ast.Expr = parse_expr("event")

        if self._should_query_event(HOGQL) and self.query.pathsFilter.pathsHogQLExpression:
            event_hogql = parse_expr(self.query.pathsFilter.pathsHogQLExpression)

        if self._should_query_event(PAGEVIEW_EVENT):
            event_hogql = parse_expr(
                "if(event = {event}, replaceRegexpAll(ifNull(properties.$current_url, ''), '(.)/$', '\\\\1'), {event_hogql})",
                {"event": ast.Constant(value=PAGEVIEW_EVENT), "event_hogql": event_hogql},
            )

        if self._should_query_event(SCREEN_EVENT):
            event_hogql = parse_expr(
                "if(event = {event}, properties.$screen_name, {event_hogql})",
                {"event": ast.Constant(value=SCREEN_EVENT), "event_hogql": event_hogql},
            )

        return event_hogql

    def handle_funnel(self) -> tuple[list, Optional[ast.Expr]]:
        if not self.query.funnelPathsFilter:
            return [], None

        funnelPathType, funnelSource, funnelStep = (
            self.query.funnelPathsFilter.funnelPathType,
            self.query.funnelPathsFilter.funnelSource,
            self.query.funnelPathsFilter.funnelStep,
        )
        funnelSourceFilter = funnelSource.funnelsFilter or FunnelsFilter()

        if funnelPathType in (
            FunnelPathType.FUNNEL_PATH_AFTER_STEP,
            FunnelPathType.FUNNEL_PATH_BEFORE_STEP,
        ):
            funnel_fields = [
                ast.Alias(alias="target_timestamp", expr=ast.Field(chain=["funnel_actors", "timestamp"])),
            ]
            interval = funnelSourceFilter.funnelWindowInterval or 14
            unit = funnelSourceFilter.funnelWindowIntervalUnit
            interval_unit = funnel_window_interval_unit_to_sql(unit)
            operator = ">=" if funnelPathType == FunnelPathType.FUNNEL_PATH_AFTER_STEP else "<="
            default_case = f"events.timestamp {operator} toTimeZone({{target_timestamp}}, 'UTC')"
            if funnelPathType == FunnelPathType.FUNNEL_PATH_AFTER_STEP and funnelStep and funnelStep < 0:
                default_case += f" + INTERVAL {interval} {interval_unit}"
            event_filter = parse_expr(
                default_case, {"target_timestamp": ast.Field(chain=["funnel_actors", "timestamp"])}
            )
            return funnel_fields, event_filter
        elif funnelPathType == FunnelPathType.FUNNEL_PATH_BETWEEN_STEPS:
            funnel_fields = [
                ast.Alias(alias="min_timestamp", expr=ast.Field(chain=["funnel_actors", "min_timestamp"])),
                ast.Alias(alias="max_timestamp", expr=ast.Field(chain=["funnel_actors", "max_timestamp"])),
            ]
            event_filter = ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["events", "timestamp"]),
                        right=ast.Field(chain=["funnel_actors", "min_timestamp"]),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.LtEq,
                        left=ast.Field(chain=["events", "timestamp"]),
                        right=ast.Field(chain=["funnel_actors", "max_timestamp"]),
                    ),
                ]
            )
            return funnel_fields, event_filter
        else:
            raise ValueError("Unexpected `funnelPathType` for funnel path filter.")

    def funnel_join(self) -> ast.JoinExpr:
        if not self.query.funnelPathsFilter:
            raise ValueError("Funnel paths filter is required for funnel paths.")

        from posthog.hogql_queries.insights.insight_actors_query_runner import InsightActorsQueryRunner

        funnelPathType, funnelSource, funnelStep = (
            self.query.funnelPathsFilter.funnelPathType,
            self.query.funnelPathsFilter.funnelSource,
            self.query.funnelPathsFilter.funnelStep,
        )

        actor_query = FunnelsActorsQuery(source=funnelSource, funnelStep=funnelStep)
        actors_query_runner = InsightActorsQueryRunner(
            query=actor_query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        assert isinstance(actors_query_runner.source_runner, FunnelsQueryRunner)
        assert actors_query_runner.source_runner.context is not None
        actors_query_runner.source_runner.context.includeTimestamp = funnelPathType in (
            FunnelPathType.FUNNEL_PATH_AFTER_STEP,
            FunnelPathType.FUNNEL_PATH_BEFORE_STEP,
        )
        actors_query_runner.source_runner.context.includePrecedingTimestamp = (
            funnelPathType == FunnelPathType.FUNNEL_PATH_BETWEEN_STEPS
        )
        actors_query = actors_query_runner.to_query()

        return ast.JoinExpr(
            table=ast.Field(chain=["events"]),
            next_join=ast.JoinExpr(
                table=actors_query,
                join_type="INNER JOIN",
                alias="funnel_actors",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["events", "person_id"]),
                        right=ast.Field(chain=["funnel_actors", "actor_id"]),
                    ),
                    constraint_type="ON",
                ),
            ),
        )

    def paths_events_query(self) -> ast.SelectQuery:
        event_filters = []
        pathReplacements: list[PathCleaningFilter] = []

        event_hogql = self.construct_event_hogql()
        event_conditional = parse_expr("ifNull({event_hogql}, '') AS path_item_ungrouped", {"event_hogql": event_hogql})

        funnel_fields, funnel_event_filter = self.handle_funnel()
        if funnel_event_filter:
            event_filters.append(funnel_event_filter)

        fields = [
            ast.Field(chain=["events", "timestamp"]),
            ast.Field(chain=["events", "person_id"]),
            *funnel_fields,
            event_conditional,
            *[ast.Field(chain=["events", field]) for field in self.extra_event_fields],
            *[
                ast.Alias(
                    alias=field,
                    expr=ast.Call(
                        name="ifNull",
                        args=[ast.Field(chain=["events", "properties", f"${field}"]), ast.Constant(value="")],
                    ),
                )
                for field in self.extra_event_properties
            ],
        ]

        final_path_item_column = "path_item_ungrouped"

        if (
            self.query.pathsFilter.pathReplacements
            and self.team.path_cleaning_filters
            and len(self.team.path_cleaning_filters) > 0
        ):
            pathReplacements.extend(self.team.path_cleaning_filter_models())

        if self.query.pathsFilter.localPathCleaningFilters and len(self.query.pathsFilter.localPathCleaningFilters) > 0:
            pathReplacements.extend(self.query.pathsFilter.localPathCleaningFilters)

        if len(pathReplacements) > 0:
            final_path_item_column = "path_item_cleaned"

            for idx, replacement in enumerate(pathReplacements):
                source_path_item_column = "path_item_ungrouped" if idx == 0 else f"path_item_{idx - 1}"
                result_path_item_column = (
                    "path_item_cleaned" if idx == len(pathReplacements) - 1 else f"path_item_{idx}"
                )

                fields.append(
                    ast.Alias(
                        alias=result_path_item_column,
                        expr=ast.Call(
                            name="replaceRegexpAll",
                            args=[
                                ast.Field(chain=[source_path_item_column]),
                                ast.Constant(value=replacement.regex),
                                ast.Constant(value=replacement.alias),
                            ],
                        ),
                    )
                )

        fields += [
            ast.Alias(
                alias="groupings",
                expr=ast.Constant(value=self.query.pathsFilter.pathGroupings or None),
            ),
            ast.Alias(
                alias="group_index",
                expr=ast.Call(
                    name="multiMatchAnyIndex",
                    args=[ast.Field(chain=[final_path_item_column]), ast.Constant(value=self.regex_groupings or None)],
                ),
            ),
            ast.Alias(
                alias="path_item",
                expr=parse_expr(
                    "if(group_index > 0, groupings[group_index], {final_path_item_column}) AS path_item",
                    {"final_path_item_column": ast.Field(chain=[final_path_item_column])},
                ),
            ),
        ]

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

        query = ast.SelectQuery(
            select=fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=event_filters + self._get_event_query()),
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["person_id"])),
                ast.OrderExpr(expr=ast.Field(chain=["events", "timestamp"])),
            ],
        )

        if funnel_fields:
            query.select_from = self.funnel_join()

        if self.query.samplingFactor is not None and isinstance(self.query.samplingFactor, float) and query.select_from:
            query.select_from.sample = ast.SampleExpr(
                sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))
            )

        return query

    def date_filter_expr(self) -> ast.Expr:
        field_to_compare = ast.Field(chain=["events", "timestamp"])
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=field_to_compare,
                    right=self.query_date_range.date_from_to_start_of_interval_hogql(),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=field_to_compare,
                    right=self.query_date_range.date_to_as_hogql(),
                ),
            ]
        )

    def get_array_compacting_function(self) -> Literal["arrayResize", "arraySlice"]:
        if self.query.pathsFilter.endPoint:
            return "arrayResize"

        return "arraySlice"

    def get_filtered_path_ordering(self) -> list[ast.Expr]:
        fields = {
            "compact_path": "path",
            "timings": "timings",
            **{f: f for f in self.extra_event_fields_and_properties},
        }
        expressions = (
            [
                ast.Alias(
                    alias=f"filtered_{field}",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Field(chain=["target_index"]),
                                right=ast.Constant(value=0),
                            ),
                            ast.Call(
                                name=self.get_array_compacting_function(),
                                args=[ast.Field(chain=[orig]), ast.Field(chain=["target_index"])],
                            ),
                            ast.Field(chain=[orig]),
                        ],
                    ),
                ),
                ast.Alias(
                    alias=f"limited_{field}",
                    expr=ast.Call(
                        name="arraySlice",
                        args=[
                            ast.Field(chain=[f"filtered_{field}"]),
                            *(
                                [ast.Constant(value=-1 * self.event_in_session_limit)]
                                if self.query.pathsFilter.endPoint
                                else [
                                    ast.Constant(value=1),
                                    ast.Constant(value=self.event_in_session_limit),
                                ]
                            ),
                        ],
                    ),
                ),
            ]
            for orig, field in fields.items()
        )
        return list(itertools.chain.from_iterable(expressions))

    def get_start_end_filtered_limited(self) -> list[ast.Expr]:
        fields = {
            "compact_path": "path",
            "timings": "timings",
            **{f: f for f in self.extra_event_fields_and_properties},
        }
        expressions = (
            [
                ast.Alias(
                    alias=f"start_filtered_{field}",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Field(chain=["start_target_index"]),
                                right=ast.Constant(value=0),
                            ),
                            ast.Call(
                                name="arraySlice",
                                args=[ast.Field(chain=[orig]), ast.Field(chain=["start_target_index"])],
                            ),
                            ast.Field(chain=[orig]),
                        ],
                    ),
                ),
                ast.Alias(
                    alias=f"filtered_{field}",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Field(chain=["end_target_index"]),
                                right=ast.Constant(value=0),
                            ),
                            ast.Call(
                                name="arrayResize",
                                args=[
                                    ast.Field(chain=[f"start_filtered_{field}"]),
                                    ast.Field(chain=["end_target_index"]),
                                ],
                            ),
                            ast.Field(chain=[f"start_filtered_{field}"]),
                        ],
                    ),
                ),
                ast.Alias(
                    alias=f"limited_{field}",
                    expr=parse_expr(
                        expr=(
                            "if(length({field}) > {event_in_session_limit}, arrayConcat(arraySlice({field}, 1, intDiv({event_in_session_limit}, 2)), ['...'], arraySlice({field}, (-1)*intDiv({event_in_session_limit}, 2), intDiv({event_in_session_limit}, 2))), {field})"
                            if field == "path"
                            else "if(length({field}) > {event_in_session_limit}, arrayConcat(arraySlice({field}, 1, intDiv({event_in_session_limit}, 2)), [{field}[1+intDiv({event_in_session_limit}, 2)]], arraySlice({field}, (-1)*intDiv({event_in_session_limit}, 2), intDiv({event_in_session_limit}, 2))), {field})"
                        ),
                        placeholders={
                            "field": ast.Field(chain=[f"filtered_{field}"]),
                            "event_in_session_limit": ast.Constant(value=self.event_in_session_limit),
                        },
                    ),
                ),
            ]
            for orig, field in fields.items()
        )
        return list(itertools.chain.from_iterable(expressions))

    def get_target_clause(self) -> list[ast.Expr]:
        if self.query.pathsFilter.startPoint and self.query.pathsFilter.endPoint:
            clauses: list[ast.Expr] = [
                ast.Alias(
                    alias=f"start_target_index",
                    expr=ast.Call(
                        name="indexOf",
                        args=[
                            ast.Field(chain=["compact_path"]),
                            ast.Constant(value=self.query.pathsFilter.startPoint),
                        ],
                    ),
                ),
            ]
            filtered_limited = self.get_start_end_filtered_limited()
            # We need a special order of fields due to dependencies
            clauses.append(filtered_limited[0])
            clauses.append(
                ast.Alias(
                    alias=f"end_target_index",
                    expr=ast.Call(
                        name="indexOf",
                        args=[
                            ast.Field(chain=["start_filtered_path"]),
                            ast.Constant(value=self.query.pathsFilter.endPoint),
                        ],
                    ),
                ),
            )
            clauses.extend(filtered_limited[1:])
            return clauses
        else:
            return self.get_filtered_path_ordering()

    def get_session_threshold_clause(self) -> ast.Expr:
        if self.query.funnelPathsFilter:
            funnelSourceFilter = self.query.funnelPathsFilter.funnelSource.funnelsFilter or FunnelsFilter()

            interval = 14
            interval_unit = FunnelConversionWindowTimeUnit.DAY

            if funnelSourceFilter.funnelWindowInterval:
                interval = funnelSourceFilter.funnelWindowInterval
                unit = funnelSourceFilter.funnelWindowIntervalUnit
                interval_unit = funnel_window_interval_unit_to_sql(unit)  # type: ignore

            return parse_expr(
                f"arraySplit(x -> if(toDateTime('2018-01-01') + toIntervalSecond(_toInt64(x.3)) < toDateTime('2018-01-01') + INTERVAL {interval} {interval_unit}, 0, 1), paths_tuple)"
            )

        return parse_expr(
            "arraySplit(x -> if(x.3 < ({session_time_threshold}), 0, 1), paths_tuple)",
            {"session_time_threshold": ast.Constant(value=SESSION_TIME_THRESHOLD_DEFAULT_SECONDS)},
        )

    def paths_per_person_query(self) -> ast.SelectQuery:
        target_point = self.query.pathsFilter.endPoint or self.query.pathsFilter.startPoint
        target_point = (
            target_point[:-1] if target_point and len(target_point) > 1 and target_point.endswith("/") else target_point
        )

        path_tuples_expr = ast.Call(
            name="arrayZip",
            args=[
                ast.Field(chain=["path_list"]),
                ast.Field(chain=["timing_list"]),
                ast.Call(
                    name="arrayDifference",
                    args=[ast.Field(chain=["timing_list"])],
                ),
                *[ast.Field(chain=[f"{f}_list"]) for f in self.extra_event_fields_and_properties],
            ],
        )

        placeholders = {
            "path_event_query": self.paths_events_query(),
            "boundary_event_filter": ast.Constant(value=None),
            "target_point": ast.Constant(value=target_point),
            "session_threshold_clause": self.get_session_threshold_clause(),
            "path_tuples_expr": path_tuples_expr,
        }
        select = cast(
            ast.SelectQuery,
            parse_select(
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
                        /* more arrayFilter(x) added below if required */
                        arrayFilter((x,y)->y, path_basic, mapping) as compact_path,
                        indexOf(compact_path, {target_point}) as target_index
                    FROM (
                        SELECT
                            person_id,
                            path_time_tuple.1 as path_basic,
                            path_time_tuple.2 as time,
                            /* path_time_tuple.x added below if required */
                            session_index,
                            {path_tuples_expr} as paths_tuple,
                            {session_threshold_clause} as session_paths
                        FROM (
                            SELECT
                                person_id,
                                groupArray(timestamp) as timing_list,
                                groupArray(path_item) as path_list
                                /* groupArray(x) added below if required */
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
            ),
        )
        assert select.select_from is not None
        table = cast(ast.SelectQuery, select.select_from.table)

        select.select.extend(
            [
                ast.Alias(
                    alias=field,
                    expr=ast.Field(chain=[f"final_{field}"]),
                )
                for field in self.extra_event_fields_and_properties
            ]
        )

        # Extra joined path tuple select statements
        table.select.extend(
            [
                ast.Alias(
                    alias=f"final_{field}",
                    expr=ast.TupleAccess(tuple=ast.Field(chain=["joined_path_tuple"]), index=i + 4),
                )
                for i, field in enumerate(self.extra_event_fields_and_properties)
            ]
        )

        # Extra arrayFilter(x)
        table.select.extend(
            [
                ast.Alias(
                    alias=field,
                    expr=ast.Call(
                        name="arrayFilter",
                        args=[
                            ast.Lambda(args=["x", "y"], expr=ast.Field(chain=["y"])),
                            ast.Field(chain=[f"{field}_items"]),
                            ast.Field(chain=["mapping"]),
                        ],
                    ),
                )
                for field in self.extra_event_fields_and_properties
            ]
        )

        table.select.extend(self.get_target_clause())

        # Extra path_time_tuple.x
        table.select_from.table.select.extend(  # type: ignore[union-attr]
            [
                ast.Alias(
                    alias=f"{field}_items",
                    expr=ast.TupleAccess(tuple=ast.Field(chain=["path_time_tuple"]), index=i + 4),
                )
                for i, field in enumerate(self.extra_event_fields_and_properties)
            ]
        )
        # Extra groupArray(x)
        table.select_from.table.select_from.table.select.extend(  # type: ignore[union-attr]
            [
                ast.Alias(alias=f"{field}_list", expr=ast.Call(name="groupArray", args=[ast.Field(chain=[field])]))
                for field in self.extra_event_fields_and_properties
            ]
        )

        other_selects = [
            "arrayDifference(limited_timings) as timings_diff",
            "concat(toString(length(limited_path)), '_', limited_path[-1]) as path_dropoff_key /* last path item */",
        ]
        table.select.extend([parse_expr(s, placeholders) for s in other_selects])

        table.select.append(
            ast.Alias(
                alias="limited_path_timings",
                expr=ast.Call(
                    name="arrayZip",
                    args=[
                        ast.Field(chain=["limited_path"]),
                        ast.Field(chain=["timings_diff"]),
                        ast.Call(
                            name="arrayPopBack",
                            args=[
                                ast.Call(
                                    name="arrayPushFront",
                                    args=[
                                        ast.Field(chain=["limited_path"]),
                                        ast.Constant(value=""),
                                    ],
                                )
                            ],
                        ),
                        *[ast.Field(chain=[f"limited_{field}"]) for field in self.extra_event_fields_and_properties],
                    ],
                ),
            )
        )

        if self.query.pathsFilter.endPoint and self.query.pathsFilter.startPoint:
            table.where = parse_expr("start_target_index > 0 AND end_target_index > 0")
        elif self.query.pathsFilter.endPoint or self.query.pathsFilter.startPoint:
            table.where = parse_expr("target_index > 0")

        return select

    def get_edge_weight_exprs(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []
        if self.query.pathsFilter.minEdgeWeight:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["event_count"]),
                    right=ast.Constant(value=self.query.pathsFilter.minEdgeWeight),
                )
            )
        if self.query.pathsFilter.maxEdgeWeight:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["event_count"]),
                    right=ast.Constant(value=self.query.pathsFilter.maxEdgeWeight),
                )
            )
        return conditions

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        placeholders: dict[str, ast.Expr] = {
            "paths_per_person_query": self.paths_per_person_query(),
        }
        with self.timings.measure("paths_query"):
            paths_query = cast(
                ast.SelectQuery,
                parse_select(
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
                ),
            )

            conditions = self.get_edge_weight_exprs()
            if conditions:
                paths_query.having = ast.And(exprs=conditions)

            paths_query.limit = ast.Constant(value=self.query.pathsFilter.edgeLimit or EDGE_LIMIT_DEFAULT)

        return paths_query

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

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

    def validate_results(self, results):
        # Query guarantees results list to be:
        # 1. Directed, Acyclic Tree where each node has only 1 child
        # 2. All start nodes beginning with 1_

        seen = set()  # source nodes that have been traversed
        edges = defaultdict(list)
        validated_results = []
        starting_nodes_stack = []

        for result in results:
            edges[result[0]].append(result[1])
            if result[0].startswith("1_"):
                # All nodes with 1_ are valid starting nodes
                starting_nodes_stack.append(result[0])

        while starting_nodes_stack:
            current_node = starting_nodes_stack.pop()
            seen.add(current_node)

            for node in edges[current_node]:
                if node not in seen:
                    starting_nodes_stack.append(node)

        for result in results:
            if result[0] in seen:
                validated_results.append(result)

        return validated_results

    def _calculate(self) -> PathsQueryResponse:
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="PathsQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=HogQLGlobalSettings(
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY
            ),  # Make sure funnel queries never OOM
        )

        response.results = self.validate_results(response.results)

        assert response.results is not None
        results = (
            {
                "source": source,
                "target": target,
                "value": correct_result_for_sampling(value, self.query.samplingFactor),
                "average_conversion_time": avg_conversion_time * 1000.0,
            }
            for source, target, value, avg_conversion_time in response.results
        )

        return PathsQueryResponse(results=results, timings=response.timings, hogql=hogql, modifiers=self.modifiers)

    @property
    def extra_event_fields_and_properties(self) -> list[str]:
        return self.extra_event_fields + self.extra_event_properties

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # To include matching_events, we need to add extra fields and properties
        # TODO: Make sure going via self is the best way to do this
        self.extra_event_fields = ["uuid", "timestamp"]
        self.extra_event_properties = ["session_id", "window_id"]

        path_per_person_query = self.paths_per_person_query()

        conditions = []
        if self.query.pathsFilter.pathDropoffKey:
            conditions.append(
                parse_expr(
                    "path_dropoff_key = {key} AND path_dropoff_key = path_key",
                    {"key": ast.Constant(value=self.query.pathsFilter.pathDropoffKey)},
                )
            )
        else:
            if self.query.pathsFilter.pathStartKey:
                conditions.append(
                    parse_expr(
                        "last_path_key = {key}",
                        {"key": ast.Constant(value=self.query.pathsFilter.pathStartKey)},
                    )
                )
            if self.query.pathsFilter.pathEndKey:
                conditions.append(
                    parse_expr(
                        "path_key = {key}",
                        {"key": ast.Constant(value=self.query.pathsFilter.pathEndKey)},
                    )
                )
            else:
                conditions.append(parse_expr("1=1"))

        actors_query = parse_select(
            """
                SELECT
                    person_id as actor_id,
                    groupUniqArray(100)((timestamp, uuid, session_id, window_id)) as matching_events,
                    COUNT(*) as event_count
                FROM {paths_per_person_query}
                WHERE {conditions}
                GROUP BY person_id
            """,
            placeholders={
                "paths_per_person_query": path_per_person_query,
                "conditions": ast.And(exprs=conditions),
            },
            timings=self.timings,
        )
        return actors_query
