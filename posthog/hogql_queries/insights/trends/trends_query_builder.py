from typing import cast

import posthoganalytics

from posthog.schema import (
    ActionsNode,
    Breakdown as BreakdownSchema,
    ChartDisplayType,
    DataWarehouseNode,
    DataWarehousePropertyFilter,
    EventsNode,
    HogQLQueryModifiers,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext, get_breakdown_limit_for_context
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.insights.data_warehouse_mixin import DataWarehouseInsightQueryMixin
from posthog.hogql_queries.insights.trends.aggregation_operations import AggregationOperations
from posthog.hogql_queries.insights.trends.breakdown import (
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_STRING_LABEL,
    Breakdown,
)
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.utils import is_groups_math, series_event_name
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.action.action import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team


class TrendsQueryBuilder(DataWarehouseInsightQueryMixin):
    query: TrendsQuery
    team: Team
    query_date_range: QueryDateRange
    series: EventsNode | ActionsNode | DataWarehouseNode
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext

    def __init__(
        self,
        trends_query: TrendsQuery,
        team: Team,
        query_date_range: QueryDateRange,
        series: EventsNode | ActionsNode | DataWarehouseNode,
        timings: HogQLTimings,
        modifiers: HogQLQueryModifiers,
        limit_context: LimitContext = LimitContext.QUERY,
    ):
        self.query = trends_query
        self.team = team
        self.query_date_range = query_date_range
        self.series = series
        self.timings = timings
        self.modifiers = modifiers
        self.limit_context = limit_context

    def build_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        events_query = self._base_events_query()
        inner_query = self._inner_select_query(inner_query=events_query)

        if self._trends_display.is_total_value():
            if not self.breakdown.enabled:
                return events_query
            return self._total_value_by_breakdown_query(inner_query=inner_query)

        return self._outer_select_query(inner_query=inner_query)

    def _total_value_by_breakdown_query(self, inner_query: ast.SelectQuery) -> ast.SelectQuery | ast.SelectSetQuery:
        rank_query = cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    count as total,
                    breakdown_value as breakdown_value,
                    row_number() OVER (ORDER BY total DESC) as row_number
                FROM {inner_query}
                ORDER BY
                    total DESC,
                    breakdown_value ASC
                """,
                placeholders={
                    "inner_query": inner_query,
                },
            ),
        )

        return parse_select(
            """
            SELECT
                SUM(total) AS total,
                {breakdown_select}
            FROM
                {rank_query}
            WHERE {breakdown_filter}
            GROUP BY breakdown_value
            ORDER BY
                {breakdown_order_by},
                total DESC,
                breakdown_value ASC
            """,
            placeholders={
                "breakdown_select": self._breakdown_outer_query_select(
                    self.breakdown, breakdown_limit=self._get_breakdown_limit() + 1
                ),
                "rank_query": rank_query,
                "breakdown_filter": self._breakdown_outer_query_filter(self.breakdown),
                "breakdown_order_by": self._breakdown_query_order_by(self.breakdown),
            },
        )

    def _outer_select_query(self, inner_query: ast.SelectQuery) -> ast.SelectQuery | ast.SelectSetQuery:
        if self.breakdown.enabled and self._team_flag_fewer_array_ops():
            if self.breakdown.is_multiple_breakdown:
                breakdown_count = len(self.breakdown.field_exprs)
                breakdown_other_expr = parse_expr(
                    str([BREAKDOWN_OTHER_STRING_LABEL] * breakdown_count),
                )
            else:
                breakdown_other_expr = ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL)

            breakdown_limit = None  # TODO: Investigate what this override is used for
            breakdown_limit_expr = ast.Constant(value=breakdown_limit or self._get_breakdown_limit())

            is_cumulative = self._trends_display.display_type == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE

            return parse_select(
                f"""
                WITH
                (
                    -- Raw per-day breakdown rows
                    SELECT * FROM {{inner_query}}
                ) AS breakdown_series,
                (
                    -- Aggregate totals per breakdown for ranking
                    SELECT
                        breakdown_value,
                        sum(count) AS total_count_for_breakdown,
                        {{breakdown_order}} AS ordering
                    FROM breakdown_series
                    GROUP BY breakdown_value
                ) AS totals_per_breakdown,
                (
                    -- Global rank applied to aggregated totals
                    SELECT
                        breakdown_value,
                        ordering,
                        total_count_for_breakdown,
                        row_number() OVER (
                            ORDER BY ordering ASC, total_count_for_breakdown DESC, breakdown_value ASC
                        ) AS breakdown_rank
                    FROM totals_per_breakdown
                ) AS ranked_breakdown_totals,
                (
                    -- Attach ranks back to per-day rows
                    SELECT
                        breakdown_series.*,
                        ranked_breakdown_totals.ordering,
                        ranked_breakdown_totals.breakdown_rank
                    FROM breakdown_series
                    JOIN ranked_breakdown_totals ON ranked_breakdown_totals.breakdown_value = breakdown_series.breakdown_value
                ) AS ranked_breakdown_values,
                (
                    -- Top N breakdown values
                    SELECT
                        day_start,
                        count AS value,
                        breakdown_value
                    FROM ranked_breakdown_values
                    WHERE breakdown_rank <= {{breakdown_limit}}
                ) AS top_n_breakdown_values,
                (
                    -- "Other" breakdown value
                    SELECT
                        day_start,
                        sum(count) as value,
                        {{breakdown_other}} as breakdown_value
                    FROM ranked_breakdown_values
                    WHERE breakdown_rank > {{breakdown_limit}}
                    GROUP BY breakdown_value, day_start
                ) AS other_breakdown_values,
                (
                    -- Combine and order top N and "other" breakdown values
                    SELECT * FROM (
                        SELECT * FROM top_n_breakdown_values
                        UNION ALL
                        SELECT * FROM other_breakdown_values
                    ) ORDER BY day_start, value
                ) AS top_n_and_other_breakdown_values,

                (
                    -- All dates in the range; :TODO: Reuse self._get_date_subqueries()
                    arrayMap(
                        number -> {{date_from_start_of_interval}} + {{number_interval_period}}, -- NOTE: flipped the order around to use start date
                        range(
                            0,
                            coalesce(
                                dateDiff(
                                    {{interval}},
                                    {{date_from_start_of_interval}},
                                    {{date_to_start_of_interval}}
                                )
                            ) + 1
                        )
                    )

                ) as all_dates,

                -- Transpose the results into arrays for each breakdown value
                {'SELECT date, total, breakdown_value FROM (' if is_cumulative else ''}
                SELECT
                    all_dates AS date,
                    arrayMap(d ->
                        arraySum(
                            arrayMap((v, dd) -> dd = d ? v : 0, vals, days)
                        ),
                        all_dates
                    ) AS {'values' if is_cumulative else 'total'},
                    {'arrayMap(i -> arraySum(arraySlice(values, 1, i)), arrayEnumerate(values)) AS total,' if is_cumulative else ''}
                    breakdown_value
                FROM (
                    SELECT
                        groupArray(day_start) AS days,
                        groupArray(value) AS vals,
                        breakdown_value
                    FROM top_n_and_other_breakdown_values
                    GROUP BY breakdown_value
                )
                ORDER BY {{breakdown_order}} ASC, arraySum(total) DESC, breakdown_value ASC
                {')' if is_cumulative else ''}
                """,
                {
                    "inner_query": inner_query,
                    "breakdown_other": breakdown_other_expr,
                    "breakdown_limit": breakdown_limit_expr,
                    "breakdown_order": self._breakdown_query_order_by(self.breakdown),
                    **self.query_date_range.to_placeholders(),
                },
            )

        total_array = parse_expr(
            """
            arrayMap(
                _match_date ->
                    arraySum(
                        arraySlice(
                            groupArray(ifNull(count, 0)),
                            indexOf(groupArray(day_start) as _days_for_count, _match_date) as _index,
                            arrayLastIndex(x -> x = _match_date, _days_for_count) - _index + 1
                        )
                    ),
                date
            )
        """
        )

        if self._trends_display.display_type == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE:
            # fill zeros in with the previous value
            total_array = parse_expr(
                """
            arrayFill(x -> x > 0, {total_array} )
            """,
                {"total_array": total_array},
            )

        select: list[ast.Expr] = [
            self._get_date_subqueries(),
        ]

        if (
            self.query.trendsFilter is not None
            and self.query.trendsFilter.smoothingIntervals is not None
            and self.query.trendsFilter.smoothingIntervals > 1
        ):
            rolling_average = ast.Alias(
                alias="total",
                expr=parse_expr(
                    """
                    arrayMap(
                        i -> floor(arrayAvg(
                            arraySlice(
                                total_array,
                                greatest(i-{smoothing_interval} + 1, 1),
                                least(i, {smoothing_interval})
                            )
                        )),
                        arrayEnumerate(total_array)
                    )
                """,
                    {
                        "smoothing_interval": ast.Constant(value=int(self.query.trendsFilter.smoothingIntervals)),
                        "total_array": total_array,
                    },
                ),
            )
            select = [
                *select,
                ast.Alias(alias="total_array", expr=total_array),
                rolling_average,
            ]
        else:
            select.append(ast.Alias(alias="total", expr=total_array))

        query = ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=inner_query),
        )

        query.order_by = []

        if self.breakdown.enabled:
            query.select.append(
                ast.Alias(
                    alias="breakdown_value",
                    expr=ast.Field(chain=["breakdown_value"]),
                )
            )

            query.select.append(ast.Alias(alias="row_number", expr=parse_expr("rowNumberInAllBlocks()")))
            query.group_by = [ast.Field(chain=["breakdown_value"])]

            query.order_by.append(ast.OrderExpr(expr=self._breakdown_query_order_by(self.breakdown), order="ASC"))
            query.order_by.append(
                ast.OrderExpr(expr=ast.Call(name="arraySum", args=[ast.Field(chain=["total"])]), order="DESC")
            )
            query.order_by.append(ast.OrderExpr(expr=ast.Field(chain=["breakdown_value"]), order="ASC"))

            # TODO: What happens with cohorts and this limit?
            # arrayFold is basically arrayReduce (but you can pass your own lambda function)
            # it takes result array from the outer query which looks like this (if they're grouped under "other" values):
            # [
            #   [0, 0, 1],
            #   [0, 1, 0]
            # ]
            # and turns it into
            # [0, 1, 1]
            return parse_select(
                """
                SELECT
                    groupArray(1)(date)[1] as date,
                    arrayFold(
                        (acc, x) -> arrayMap(
                            i -> acc[i] + x[i],
                            range(1, length(date) + 1)
                        ),
                        groupArray(ifNull(total, 0)),
                        arrayWithConstant(length(date), reinterpretAsFloat64(0))
                    ) as total,
                    {breakdown_select}
                FROM {outer_query}
                WHERE {breakdown_filter}
                GROUP BY breakdown_value
                ORDER BY
                    {breakdown_order_by},
                    arraySum(total) DESC,
                    breakdown_value ASC
            """,
                {
                    "breakdown_select": self._breakdown_outer_query_select(self.breakdown),
                    "outer_query": query,
                    "breakdown_filter": self._breakdown_outer_query_filter(self.breakdown),
                    "breakdown_order_by": self._breakdown_query_order_by(self.breakdown),
                },
            )

        query.order_by.append(
            ast.OrderExpr(expr=ast.Call(name="arraySum", args=[ast.Field(chain=["total"])]), order="DESC")
        )

        return query

    def _inner_select_query(self, inner_query: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery:
        query = cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    sum(total) AS count
                FROM {inner_query}
            """,
                placeholders={"inner_query": inner_query},
            ),
        )

        query.group_by = []
        query.order_by = []

        if not self._trends_display.is_total_value():
            query.select.append(ast.Field(chain=["day_start"]))
            query.group_by.append(ast.Field(chain=["day_start"]))
            query.order_by.append(ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC"))

        if self.breakdown.enabled:
            query = self._inner_breakdown_subquery(query, self.breakdown)

        if self._trends_display.should_wrap_inner_query() and (
            not self._team_flag_fewer_array_ops() or not self.breakdown.enabled
        ):
            query = self._trends_display.wrap_inner_query(query, self.breakdown.enabled)
            if self.breakdown.enabled:
                query.select.append(ast.Field(chain=["breakdown_value"]))

        return query

    def _base_events_query(
        self,
    ) -> ast.SelectQuery:
        events_filter = self._events_filter(
            ignore_breakdowns=False,
            breakdown=self.breakdown,
        )

        default_query = ast.SelectQuery(
            select=[ast.Alias(alias="total", expr=self._aggregation_operation.select_aggregation())],
            select_from=ast.JoinExpr(
                table=self._table_expr,
                alias="e",
                sample=(
                    ast.SampleExpr(sample_value=self._sample_value())
                    if not isinstance(self.series, DataWarehouseNode)
                    else None
                ),
            ),
            where=events_filter,
            group_by=[],
        )
        assert default_query.group_by is not None

        day_start = ast.Alias(
            alias="day_start",
            expr=ast.Call(
                name=f"toStartOf{self.query_date_range.interval_name.title()}", args=[ast.Field(chain=["timestamp"])]
            ),
        )

        if self._trends_display.is_total_value():
            if not self.breakdown.enabled:
                default_query.order_by = [ast.OrderExpr(expr=parse_expr("1"), order="DESC")]
        else:
            # For cumulative unique users or groups, we want to count each user or group once per query, not per day
            if (
                self.query.trendsFilter
                and self.query.trendsFilter.display == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE
                and (self.series.math == "unique_group" or self.series.math == "dau")
            ):
                day_start.expr = ast.Call(name="min", args=[day_start.expr])
                default_query.group_by.append(self._aggregation_operation.actor_id())
            else:
                default_query.group_by.append(ast.Field(chain=["day_start"]))
            default_query.select.append(day_start)

        # No breakdowns and no complex series aggregation
        if (
            not self.breakdown.enabled
            and not self._aggregation_operation.requires_query_orchestration()
            and not self._aggregation_operation.aggregating_on_session_duration()
        ):
            return default_query
        # Both breakdowns and complex series aggregation
        elif (
            self.breakdown.enabled
            and self._aggregation_operation.requires_query_orchestration()
            and not self._aggregation_operation.is_first_time_ever_math()
        ):
            orchestrator = self._aggregation_operation.get_actors_query_orchestrator(
                events_where_clause=events_filter,
                sample_value=self._sample_value(),
            )

            orchestrator.events_query_builder.extend_select(self.breakdown.column_exprs)
            orchestrator.events_query_builder.extend_group_by(self.breakdown.field_exprs)

            orchestrator.inner_select_query_builder.extend_select(self.breakdown.alias_exprs)
            orchestrator.inner_select_query_builder.extend_group_by(self.breakdown.field_exprs)

            orchestrator.parent_select_query_builder.extend_select(self.breakdown.alias_exprs)
            if (
                self._aggregation_operation.is_total_value
                and not self._aggregation_operation.is_count_per_actor_variant()
            ):
                orchestrator.parent_select_query_builder.extend_group_by(self.breakdown.field_exprs)

            return orchestrator.build()
        elif self.breakdown.enabled and self._aggregation_operation.requires_query_orchestration():
            orchestrator = self._aggregation_operation.get_first_time_math_query_orchestrator(
                events_where_clause=events_filter,
                sample_value=self._sample_value(),
                event_name_filter=self._event_or_action_where_expr(),
            )
            orchestrator.events_query_builder.extend_select(self.breakdown.column_exprs, aggregate=True)
            orchestrator.parent_query_builder.extend_select(self.breakdown.alias_exprs)
            orchestrator.parent_query_builder.extend_group_by(self.breakdown.field_exprs)
            return orchestrator.build()
        # Breakdowns and session duration math property
        elif self.breakdown.enabled and self._aggregation_operation.aggregating_on_session_duration():
            default_query.select = [
                ast.Alias(
                    alias="session_duration",
                    expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$session_duration"])]),
                ),
            ]

            default_query.group_by.append(ast.Field(chain=["$session_id"]))

            default_query.select.extend(self.breakdown.column_exprs)
            default_query.group_by.extend(self.breakdown.field_exprs)

            wrapper = self.session_duration_math_property_wrapper(default_query, self.breakdown)
            assert wrapper.group_by is not None

            if not self._trends_display.is_total_value():
                assert wrapper.group_by is not None
                assert isinstance(wrapper.select_from, ast.JoinExpr)
                assert isinstance(wrapper.select_from.table, ast.SelectQuery)
                assert wrapper.select_from.table.group_by is not None

                # can't use "default_query" directly anymore, must use "wrapper.select_from.table"
                wrapper.select_from.table.select.append(day_start)
                wrapper.select_from.table.group_by.append(ast.Field(chain=["day_start"]))

                wrapper.select.append(ast.Field(chain=["day_start"]))
                wrapper.group_by.append(ast.Field(chain=["day_start"]))

            return wrapper

        # Just breakdowns
        elif self.breakdown.enabled:
            default_query.select.extend(self.breakdown.column_exprs)
            default_query.group_by.extend(self.breakdown.field_exprs)

        # Just session duration math property
        elif self._aggregation_operation.aggregating_on_session_duration():
            default_query.select = [
                ast.Alias(
                    alias="session_duration",
                    expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$session_duration"])]),
                )
            ]
            default_query.group_by.append(ast.Field(chain=["$session_id"]))

            wrapper = self.session_duration_math_property_wrapper(default_query, self.breakdown)

            if not self._trends_display.is_total_value():
                assert wrapper.group_by is not None
                assert isinstance(wrapper.select_from, ast.JoinExpr)
                assert isinstance(wrapper.select_from.table, ast.SelectQuery)
                assert wrapper.select_from.table.group_by is not None

                # can't use "default_query" directly anymore, must use "wrapper.select_from.table"
                wrapper.select_from.table.select.append(day_start)
                wrapper.select_from.table.group_by.append(ast.Field(chain=["day_start"]))

                wrapper.select.append(ast.Field(chain=["day_start"]))
                wrapper.group_by.append(ast.Field(chain=["day_start"]))

            return wrapper
        # Just complex series aggregation
        elif self._aggregation_operation.requires_query_orchestration() and (
            self._aggregation_operation.is_first_time_ever_math()
        ):
            return self._aggregation_operation.get_first_time_math_query_orchestrator(
                events_where_clause=events_filter,
                sample_value=self._sample_value(),
                event_name_filter=self._event_or_action_where_expr(),
            ).build()
        elif self._aggregation_operation.requires_query_orchestration():
            return self._aggregation_operation.get_actors_query_orchestrator(
                events_where_clause=events_filter,
                sample_value=self._sample_value(),
            ).build()

        return default_query

    def _get_date_subqueries(self) -> ast.Expr:
        return parse_expr(
            """
            arrayMap(
                number -> {date_from_start_of_interval} + {number_interval_period}, -- NOTE: flipped the order around to use start date
                range(
                    0,
                    coalesce(
                        dateDiff(
                            {interval},
                            {date_from_start_of_interval},
                            {date_to_start_of_interval}
                        )
                    ) + 1
                )
            ) as date
        """,
            placeholders=self.query_date_range.to_placeholders(),
        )

    def _get_breakdown_limit(self) -> int:
        if self._trends_display.display_type == ChartDisplayType.WORLD_MAP:
            return 250

        return (
            self.query.breakdownFilter and self.query.breakdownFilter.breakdown_limit
        ) or get_breakdown_limit_for_context(self.limit_context)

    def _inner_breakdown_subquery(self, query: ast.SelectQuery, breakdown: Breakdown) -> ast.SelectQuery:
        assert self.query.breakdownFilter is not None  # type checking

        if not query.group_by:
            query.group_by = []

        if not query.order_by:
            query.order_by = []

        if breakdown.is_histogram_breakdown:
            query.ctes = {
                "min_max": ast.CTE(
                    name="min_max",
                    expr=self._base_events_query(),
                    cte_type="subquery",
                )
            }

            if breakdown.is_multiple_breakdown:
                breakdown_aliases = [
                    {
                        "alias": alias,
                        "histogram_bin_count": breakdown_schema.histogram_bin_count,
                    }
                    for breakdown_schema, alias in zip(
                        cast(list[BreakdownSchema], self.query.breakdownFilter.breakdowns),
                        breakdown.multiple_breakdowns_aliases,
                    )
                ]
            else:
                filter_bin_count = cast(int, self.query.breakdownFilter.breakdown_histogram_bin_count)

                breakdown_aliases = [
                    {
                        "alias": breakdown.breakdown_alias,
                        "histogram_bin_count": filter_bin_count,
                    }
                ]

            breakdown_aliases_with_histograms = [
                breakdown_alias
                for breakdown_alias in breakdown_aliases
                if isinstance(breakdown_alias.get("histogram_bin_count"), int)
            ]

            assert query.select_from is not None and isinstance(query.select_from.table, ast.SelectQuery)
            query.select_from.table.select.extend(
                [
                    # Using arrays would be more efficient here, _but_ only if there's low cardinality in breakdown_values
                    # If cardinality is high it'd blow up memory
                    # Clickhouse is reasonably clever not rereading the same data
                    parse_expr(
                        "(select {max} from min_max) as max_nums",
                        placeholders={
                            "max": ast.Array(
                                exprs=[
                                    ast.Call(name="max", args=[ast.Field(chain=[histogram_breakdown["alias"]])])
                                    for histogram_breakdown in breakdown_aliases_with_histograms
                                ]
                            )
                        },
                    ),
                    parse_expr(
                        "(select {min} from min_max) as min_nums",
                        placeholders={
                            "min": ast.Array(
                                exprs=[
                                    ast.Call(name="min", args=[ast.Field(chain=[histogram_breakdown["alias"]])])
                                    for histogram_breakdown in breakdown_aliases_with_histograms
                                ]
                            )
                        },
                    ),
                    parse_expr(
                        "arrayMap((max_num, min_num) -> max_num - min_num, arrayZip(max_nums, min_nums)) as diff"
                    ),
                    ast.Alias(
                        alias="bins",
                        expr=ast.Array(
                            exprs=[
                                ast.Constant(value=alias["histogram_bin_count"])
                                for alias in breakdown_aliases_with_histograms
                            ]
                        ),
                    ),
                    parse_expr(
                        """
                            arrayMap(
                                i -> arrayMap(x -> [
                                        ((diff[i] / bins[i]) * x) + min_nums[i],
                                        ((diff[i] / bins[i]) * (x + 1)) + min_nums[i] + if(x + 1 = bins[i], 0.01, 0)
                                    ],
                                    range(bins[i])
                                ),
                                range(1, {breakdown_count})
                            ) as buckets
                        """,
                        placeholders={
                            "breakdown_count": ast.Constant(value=len(breakdown_aliases_with_histograms) + 1),
                        },
                    ),
                ]
            )

            bucketed_breakdowns: list[ast.Expr] = []
            for breakdown_alias in breakdown_aliases:
                if not isinstance(breakdown_alias.get("histogram_bin_count"), int):
                    bucketed_breakdowns.append(ast.Field(chain=[breakdown_alias["alias"]]))
                else:
                    alias_to_index = {
                        breakdown_alias["alias"]: idx
                        for idx, breakdown_alias in enumerate(breakdown_aliases_with_histograms)
                    }

                    filter_expr = parse_expr(
                        """
                            arrayFilter(
                                x -> x[1] <= {alias} and {alias} < x[2],
                                buckets[{bucket_index}]
                            )[1]
                        """,
                        placeholders={
                            "alias": ast.Field(chain=[breakdown_alias["alias"]]),
                            "bucket_index": ast.Constant(value=alias_to_index[breakdown_alias["alias"]] + 1),
                        },
                    )

                    bucketed_breakdowns.append(
                        parse_expr(
                            """
                                empty({filter}) ? {nil} : {normalized_value}
                            """,
                            placeholders={
                                "nil": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                                "filter": filter_expr,
                                "normalized_value": breakdown.get_replace_null_values_transform(filter_expr),
                            },
                        )
                    )

            breakdown_array = ast.Array(exprs=bucketed_breakdowns)

            query.select.append(
                ast.Alias(
                    alias="breakdown_value",
                    expr=(
                        breakdown_array
                        if breakdown.is_multiple_breakdown
                        else parse_expr("{arr}[1]", placeholders={"arr": breakdown_array})
                    ),
                )
            )

            query.group_by.append(ast.Field(chain=["breakdown_value"]))
        elif breakdown.is_multiple_breakdown:
            breakdowns_list: list[ast.Expr] = []
            for alias in breakdown.multiple_breakdowns_aliases:
                breakdowns_list.append(
                    ast.Call(
                        name="ifNull",
                        args=[
                            ast.Call(name="toString", args=[ast.Field(chain=[alias])]),
                            ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                        ],
                    )
                )
                query.group_by.append(ast.Field(chain=[alias]))
            query.select.append(ast.Alias(alias="breakdown_value", expr=ast.Array(exprs=breakdowns_list)))
        else:
            query.select.append(ast.Field(chain=[breakdown.breakdown_alias]))
            query.group_by.append(ast.Field(chain=[breakdown.breakdown_alias]))

        query.order_by.append(ast.OrderExpr(expr=ast.Field(chain=["breakdown_value"]), order="ASC"))

        return query

    def _events_filter(
        self,
        breakdown: Breakdown | None,
        ignore_breakdowns: bool = False,
    ) -> ast.Expr:
        series = self.series
        filters: list[ast.Expr] = []
        is_data_warehouse_event_series = (
            isinstance(series, DataWarehouseNode)
            and self.modifiers.dataWarehouseEventsModifiers is not None
            and any(
                series.table_name == modifier.table_name for modifier in self.modifiers.dataWarehouseEventsModifiers
            )
        )

        # Dates
        if not self._aggregation_operation.requires_query_orchestration():
            date_range_placeholders = self.query_date_range.to_placeholders()
            filters.extend(
                [
                    parse_expr(
                        "timestamp >= {date_from_with_adjusted_start_of_interval}", placeholders=date_range_placeholders
                    ),
                    parse_expr("timestamp <= {date_to}", placeholders=date_range_placeholders),
                ]
            )

        # Filter by event or action name
        if not self._aggregation_operation.is_first_time_ever_math():
            event_or_action = self._event_or_action_where_expr()
            if event_or_action is not None:
                filters.append(event_or_action)

        # Filter Test Accounts
        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for property in self.team.test_account_filters:
                if is_data_warehouse_event_series:
                    property_clone = property.copy()
                    if property_clone["type"] in ("event", "person"):
                        if property_clone["type"] == "event":
                            property_clone["key"] = f"events.properties.{property_clone['key']}"
                        elif property_clone["type"] == "person":
                            property_clone["key"] = f"events.person.properties.{property_clone['key']}"
                        property_clone["type"] = "data_warehouse"
                    expr = property_to_expr(property_clone, self.team)
                    if (
                        property_clone["type"] in ("group", "element")
                        and isinstance(expr, ast.CompareOperation)
                        and isinstance(expr.left, ast.Field)
                    ):
                        expr.left.chain = ["events", *expr.left.chain]
                    filters.append(expr)
                else:
                    filters.append(property_to_expr(property, self.team))

        # Properties
        if self.query.properties is not None and self.query.properties != []:
            if is_data_warehouse_event_series:
                data_warehouse_properties = [
                    p for p in self.query.properties if isinstance(p, DataWarehousePropertyFilter)
                ]
                if data_warehouse_properties:
                    filters.append(property_to_expr(data_warehouse_properties, self.team))
            else:
                filters.append(property_to_expr(self.query.properties, self.team))

        # Series Filters
        if series.properties is not None and series.properties != []:
            filters.append(property_to_expr(series.properties, self.team))

        # Breakdown
        if not ignore_breakdowns and breakdown is not None:
            if breakdown.enabled and not breakdown.is_histogram_breakdown:
                breakdown_filter = breakdown.get_trends_query_where_filter()
                if breakdown_filter is not None:
                    filters.append(breakdown_filter)

        # Ignore empty groups
        if is_groups_math(series=series):
            filters.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["e", f"$group_{int(cast(int, self.series.math_group_type_index))}"]),
                    right=ast.Constant(value=""),
                )
            )

        if len(filters) == 0:
            return ast.Constant(value=True)

        return ast.And(exprs=filters)

    def _event_or_action_where_expr(self) -> ast.Expr | None:
        # Event name
        if series_event_name(self.series) is not None:
            return parse_expr(
                "event = {event}",
                placeholders={"event": ast.Constant(value=series_event_name(self.series))},
            )

        # Actions
        if isinstance(self.series, ActionsNode):
            try:
                action = Action.objects.get(pk=int(self.series.id), team__project_id=self.team.project_id)
                return action_to_expr(action)
            except Action.DoesNotExist:
                # If an action doesn't exist, we want to return no events
                return parse_expr("1 = 2")

        return None

    def _sample_value(self) -> ast.RatioExpr:
        if self.query.samplingFactor is None:
            return ast.RatioExpr(left=ast.Constant(value=1))

        return ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))

    def session_duration_math_property_wrapper(
        self, default_query: ast.SelectQuery, breakdown: Breakdown
    ) -> ast.SelectQuery:
        query = cast(
            ast.SelectQuery,
            parse_select(
                """
                    SELECT {aggregation_operation} AS total
                    FROM {default_query}
                """,
                placeholders={
                    "aggregation_operation": self._aggregation_operation.select_aggregation(),
                    "default_query": default_query,
                },
            ),
        )

        query.group_by = []

        if breakdown.enabled:
            query.select.extend(breakdown.alias_exprs)
            query.group_by.extend(breakdown.field_exprs)

        return query

    @cached_property
    def breakdown(self):
        return Breakdown(
            team=self.team,
            query=self.query,
            series=self.series,
            query_date_range=self.query_date_range,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

    @cached_property
    def _aggregation_operation(self) -> AggregationOperations:
        return AggregationOperations(
            self.team,
            self.series,
            self._trends_display.display_type,
            self.query_date_range,
            self._trends_display.is_total_value(),
        )

    @cached_property
    def _trends_display(self) -> TrendsDisplay:
        display = (
            self.query.trendsFilter.display
            if self.query.trendsFilter is not None and self.query.trendsFilter.display is not None
            else None
        )
        return TrendsDisplay(display)

    def _breakdown_outer_query_select(self, breakdown: Breakdown, breakdown_limit: int | None = None) -> ast.Expr:
        breakdown_limit_expr = ast.Constant(value=breakdown_limit or self._get_breakdown_limit())
        # We always add the "other" aggregation to tell if we truncated the results
        # It is then removed later
        other_label_expr = ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL)

        if breakdown.is_multiple_breakdown:
            return parse_expr(
                """
                arrayMap(i -> if(ifNull(greaterOrEquals(row_number, {breakdown_limit}), 0), {other_label}, i), breakdown_value) AS breakdown_value
                """,
                placeholders={
                    "breakdown_limit": breakdown_limit_expr,
                    "other_label": other_label_expr,
                },
            )

        return parse_expr(
            """
            if(ifNull(greaterOrEquals(row_number, {breakdown_limit}), 0), {other_label}, breakdown_value) AS breakdown_value
            """,
            placeholders={
                "breakdown_limit": breakdown_limit_expr,
                "other_label": other_label_expr,
            },
        )

    def _breakdown_query_order_by(self, breakdown: Breakdown):
        if breakdown.is_multiple_breakdown:
            return parse_expr(
                """
                if(has(breakdown_value, {other_label}), 2, if(has(breakdown_value, {nil_label}), 1, 0))
                """,
                placeholders={
                    "nil_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                    "other_label": ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
                },
            )

        return parse_expr(
            """
            breakdown_value = {other_label} ? 2 : breakdown_value = {nil_label} ? 1 : 0
            """,
            placeholders={
                "nil_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                "other_label": ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
            },
        )

    def _breakdown_outer_query_filter(self, breakdown: Breakdown):
        if breakdown.is_multiple_breakdown:
            return parse_expr(
                """
                arrayExists(x -> isNotNull(x), breakdown_value)
                """
            )
        return parse_expr(
            """
            breakdown_value IS NOT NULL
            """
        )

    def _team_flag_fewer_array_ops(self) -> bool:
        return True  # :TODO: Remove before release. Temporary override CI tests.
        return posthoganalytics.feature_enabled(
            "trends-breakdown-fewer-array-ops",
            str(self.team.uuid),
            groups={
                "organization": str(self.team.organization_id),
                "project": str(self.team.id),
            },
            group_properties={
                "organization": {
                    "id": str(self.team.organization_id),
                },
                "project": {
                    "id": str(self.team.id),
                },
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
