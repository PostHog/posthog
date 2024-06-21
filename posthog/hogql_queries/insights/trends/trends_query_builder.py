from typing import Optional, cast
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.data_warehouse_mixin import DataWarehouseInsightQueryMixin
from posthog.hogql_queries.insights.trends.aggregation_operations import (
    AggregationOperations,
)
from posthog.hogql_queries.insights.trends.breakdown import Breakdown, BREAKDOWN_OTHER_STRING_LABEL
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.utils import series_event_name
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.action.action import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.hogql.constants import get_breakdown_limit_for_context
from posthog.models.team.team import Team
from posthog.queries.trends.breakdown import BREAKDOWN_NULL_STRING_LABEL
from posthog.schema import (
    ActionsNode,
    DataWarehouseNode,
    EventsNode,
    HogQLQueryModifiers,
    TrendsQuery,
    ChartDisplayType,
)


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

    def build_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        breakdown = self._breakdown(is_actors_query=False)

        events_query: ast.SelectQuery | ast.SelectUnionQuery

        if self._trends_display.is_total_value():
            events_query = self._get_events_subquery(False, is_actors_query=False, breakdown=breakdown)
            wrapper_query = self._get_wrapper_query(events_query, breakdown=breakdown)
            return wrapper_query
        else:
            event_query = self._get_events_subquery(False, is_actors_query=False, breakdown=breakdown)

            inner_select = self._inner_select_query(inner_query=event_query, breakdown=breakdown)
            full_query = self._outer_select_query(inner_query=inner_select, breakdown=breakdown)

            return full_query

    def _get_breakdown_hide_others(self) -> bool:
        return (
            self.query.breakdownFilter.breakdown_hide_other_aggregation or False
            if self.query.breakdownFilter
            else False
        )

    def _get_wrapper_query(
        self, events_query: ast.SelectQuery, breakdown: Breakdown
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        if not breakdown.enabled:
            return events_query

        return parse_select(
            """
            SELECT
                SUM(total) AS total,
                if(ifNull(greaterOrEquals(row_number, {breakdown_limit}), 0), {other_label}, toString(breakdown_value)) AS breakdown_value
            FROM
                (
                    SELECT
                        total,
                        breakdown_value,
                        row_number() OVER (ORDER BY total DESC) as row_number
                    FROM {events_query}
                )
            WHERE breakdown_value IS NOT NULL
            GROUP BY breakdown_value
            ORDER BY
                breakdown_value = {other_label} ? 2 : breakdown_value = {nil} ? 1 : 0,
                total DESC,
                breakdown_value ASC
        """,
            placeholders={
                "events_query": events_query,
                "other_label": ast.Constant(
                    value=None if self._get_breakdown_hide_others() else BREAKDOWN_OTHER_STRING_LABEL
                ),
                "nil": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                "breakdown_limit": ast.Constant(value=self._get_breakdown_limit() + 1),
            },
        )

    def _get_date_subqueries(self) -> ast.Expr:
        return parse_expr(
            """
            arrayMap(
                number -> {date_from_start_of_interval} + {plus_interval}, -- NOTE: flipped the order around to use start date
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
            placeholders={
                **self.query_date_range.to_placeholders(),
                "plus_interval": self.query_date_range.number_interval_periods(),
            },
        )

    def _get_events_subquery(
        self,
        no_modifications: Optional[bool],
        is_actors_query: bool,
        breakdown: Breakdown,
        actors_query_time_frame: Optional[str] = None,
    ) -> ast.SelectQuery:
        events_filter = self._events_filter(
            ignore_breakdowns=False,
            breakdown=breakdown,
            is_actors_query=is_actors_query,
            actors_query_time_frame=actors_query_time_frame,
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

        # If it's total value, we should order the results as there's no outer query to do the ordering
        if self._trends_display.is_total_value():
            default_query.order_by = [ast.OrderExpr(expr=parse_expr("1"), order="DESC")]
            if breakdown.enabled:
                default_query.order_by.append(ast.OrderExpr(expr=ast.Field(chain=["breakdown_value"]), order="DESC"))

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
            not breakdown.enabled
            and not self._aggregation_operation.requires_query_orchestration()
            and not self._aggregation_operation.aggregating_on_session_duration()
        ) or no_modifications is True:
            return default_query
        # Both breakdowns and complex series aggregation
        elif breakdown.enabled and self._aggregation_operation.requires_query_orchestration():
            orchestrator = self._aggregation_operation.get_query_orchestrator(
                events_where_clause=events_filter,
                sample_value=self._sample_value(),
            )

            orchestrator.events_query_builder.append_select(breakdown.column_expr())
            orchestrator.events_query_builder.append_group_by(ast.Field(chain=["breakdown_value"]))

            orchestrator.inner_select_query_builder.append_select(ast.Field(chain=["breakdown_value"]))
            orchestrator.inner_select_query_builder.append_group_by(ast.Field(chain=["breakdown_value"]))

            orchestrator.parent_select_query_builder.append_select(ast.Field(chain=["breakdown_value"]))

            if (
                self._aggregation_operation.is_total_value
                and not self._aggregation_operation.is_count_per_actor_variant()
            ):
                orchestrator.parent_select_query_builder.append_group_by(ast.Field(chain=["breakdown_value"]))

            return orchestrator.build()
        # Breakdowns and session duration math property
        elif breakdown.enabled and self._aggregation_operation.aggregating_on_session_duration():
            default_query.select = [
                ast.Alias(
                    alias="session_duration",
                    expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$session_duration"])]),
                ),
                breakdown.column_expr(),
            ]

            default_query.group_by.extend([ast.Field(chain=["$session_id"]), ast.Field(chain=["breakdown_value"])])

            wrapper = self.session_duration_math_property_wrapper(default_query)
            assert wrapper.group_by is not None

            if not self._trends_display.is_total_value():
                default_query.select.append(day_start)
                default_query.group_by.append(ast.Field(chain=["day_start"]))

                wrapper.select.append(ast.Field(chain=["day_start"]))
                wrapper.group_by.append(ast.Field(chain=["day_start"]))

            wrapper.select.append(ast.Field(chain=["breakdown_value"]))
            wrapper.group_by.append(ast.Field(chain=["breakdown_value"]))

            return wrapper

        # Just breakdowns
        elif breakdown.enabled:
            breakdown_expr = breakdown.column_expr()

            default_query.select.append(breakdown_expr)
            default_query.group_by.append(ast.Field(chain=["breakdown_value"]))
        # Just session duration math property
        elif self._aggregation_operation.aggregating_on_session_duration():
            default_query.select = [
                ast.Alias(
                    alias="session_duration",
                    expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$session_duration"])]),
                )
            ]
            default_query.group_by.append(ast.Field(chain=["$session_id"]))

            wrapper = self.session_duration_math_property_wrapper(default_query)

            if not self._trends_display.is_total_value():
                assert wrapper.group_by is not None

                default_query.select.append(day_start)
                default_query.group_by.append(ast.Field(chain=["day_start"]))

                wrapper.select.append(ast.Field(chain=["day_start"]))
                wrapper.group_by.append(ast.Field(chain=["day_start"]))

            return wrapper
        # Just complex series aggregation
        elif self._aggregation_operation.requires_query_orchestration():
            return self._aggregation_operation.get_query_orchestrator(
                events_where_clause=events_filter,
                sample_value=self._sample_value(),
            ).build()

        return default_query

    def _outer_select_query(
        self, breakdown: Breakdown, inner_query: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        total_array = parse_expr(
            """
            arrayMap(
                _match_date ->
                    arraySum(
                        arraySlice(
                            groupArray(count),
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

        query.order_by = [
            ast.OrderExpr(expr=ast.Call(name="arraySum", args=[ast.Field(chain=["total"])]), order="DESC")
        ]

        if breakdown.enabled:
            query.select.append(
                ast.Alias(
                    alias="breakdown_value",
                    expr=ast.Call(
                        name="ifNull",
                        args=[
                            ast.Call(name="toString", args=[ast.Field(chain=["breakdown_value"])]),
                            ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                        ],
                    ),
                )
            )
            query.select.append(ast.Alias(alias="row_number", expr=parse_expr("rowNumberInAllBlocks()")))
            query.group_by = [ast.Field(chain=["breakdown_value"])]

            query.order_by.append(ast.OrderExpr(expr=ast.Field(chain=["breakdown_value"]), order="ASC"))

            # TODO: What happens with cohorts and this limit?
            if not breakdown.is_histogram_breakdown:
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
                            groupArray(total),
                            arrayWithConstant(length(date), reinterpretAsFloat64(0))
                        ) as total,
                        if(row_number >= {breakdown_limit}, {other_label}, toString(breakdown_value)) as breakdown_value
                    FROM {outer_query}
                    WHERE breakdown_value IS NOT NULL
                    GROUP BY breakdown_value
                    ORDER BY
                        breakdown_value = {other_label} ? 2 : breakdown_value = {nil} ? 1 : 0,
                        arraySum(total) DESC,
                        breakdown_value ASC
                """,
                    {
                        "outer_query": query,
                        "breakdown_limit": ast.Constant(value=self._get_breakdown_limit()),
                        "other_label": ast.Constant(
                            value=None if self._get_breakdown_hide_others() else BREAKDOWN_OTHER_STRING_LABEL
                        ),
                        "nil": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                    },
                )
        return query

    def _get_breakdown_limit(self) -> int:
        if self._trends_display.display_type == ChartDisplayType.WORLD_MAP:
            return 250

        return (
            self.query.breakdownFilter and self.query.breakdownFilter.breakdown_limit
        ) or get_breakdown_limit_for_context(self.limit_context)

    def _inner_select_query(
        self, breakdown: Breakdown, inner_query: ast.SelectQuery | ast.SelectUnionQuery
    ) -> ast.SelectQuery:
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

        if breakdown.enabled:
            if breakdown.is_histogram_breakdown:
                histogram_bin_count = (
                    self.query.breakdownFilter.breakdown_histogram_bin_count if self.query.breakdownFilter else None
                )
                query.ctes = {
                    "min_max": ast.CTE(
                        name="min_max",
                        expr=self._get_events_subquery(
                            no_modifications=False, is_actors_query=False, breakdown=breakdown
                        ),
                        cte_type="subquery",
                    )
                }
                query.select.extend(
                    [
                        # Using arrays would be more efficient here, _but_ only if there's low cardinality in breakdown_values
                        # If cardinality is high it'd blow up memory
                        # Clickhouse is reasonably clever not rereading the same data
                        parse_expr("(select max(breakdown_value) from min_max) as max_num"),
                        parse_expr("(select min(breakdown_value) from min_max) as min_num"),
                        parse_expr("max_num - min_num as diff"),
                        parse_expr(f"{histogram_bin_count} as bins"),
                        parse_expr("""
                        arrayMap(
                            x -> [
                               ((diff / bins) * x) + min_num,
                               ((diff / bins) * (x + 1)) + min_num + if(x + 1 = bins, 0.01, 0)
                            ],
                            range(bins)
                        ) as buckets
                    """),
                        parse_expr("""arrayFilter(
                            x ->
                                x[1] <= breakdown_value and breakdown_value < x[2],
                        buckets
                        )[1] as breakdown_value
                    """),
                    ]
                )
            else:
                query.select.append(ast.Field(chain=["breakdown_value"]))
            query.group_by.append(ast.Field(chain=["breakdown_value"]))
            query.order_by.append(ast.OrderExpr(expr=ast.Field(chain=["breakdown_value"]), order="ASC"))

        if self._trends_display.should_wrap_inner_query():
            query = self._trends_display.wrap_inner_query(query, breakdown.enabled)
            if breakdown.enabled:
                query.select.append(ast.Field(chain=["breakdown_value"]))

        return query

    def _events_filter(
        self,
        is_actors_query: bool,
        breakdown: Breakdown | None,
        ignore_breakdowns: bool = False,
        actors_query_time_frame: Optional[str] = None,
    ) -> ast.Expr:
        series = self.series
        filters: list[ast.Expr] = []

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

        # Series
        if series_event_name(self.series) is not None:
            filters.append(
                parse_expr(
                    "event = {event}",
                    placeholders={"event": ast.Constant(value=series_event_name(self.series))},
                )
            )

        # Filter Test Accounts
        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for property in self.team.test_account_filters:
                filters.append(property_to_expr(property, self.team))

        # Properties
        if self.query.properties is not None and self.query.properties != []:
            filters.append(property_to_expr(self.query.properties, self.team))

        # Series Filters
        if series.properties is not None and series.properties != []:
            filters.append(property_to_expr(series.properties, self.team))

        # Actions
        if isinstance(series, ActionsNode):
            try:
                action = Action.objects.get(pk=int(series.id), team=self.team)
                filters.append(action_to_expr(action))
            except Action.DoesNotExist:
                # If an action doesn't exist, we want to return no events
                filters.append(parse_expr("1 = 2"))

        # Breakdown
        if not ignore_breakdowns and breakdown is not None:
            if breakdown.enabled and not breakdown.is_histogram_breakdown:
                breakdown_filter = breakdown.events_where_filter()
                if breakdown_filter is not None:
                    filters.append(breakdown_filter)

        # Ignore empty groups
        if series.math == "unique_group" and series.math_group_type_index is not None:
            filters.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["e", f"$group_{int(series.math_group_type_index)}"]),
                    right=ast.Constant(value=""),
                )
            )

        if len(filters) == 0:
            return ast.Constant(value=True)

        return ast.And(exprs=filters)

    def _sample_value(self) -> ast.RatioExpr:
        if self.query.samplingFactor is None:
            return ast.RatioExpr(left=ast.Constant(value=1))

        return ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))

    def session_duration_math_property_wrapper(self, default_query: ast.SelectQuery) -> ast.SelectQuery:
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
        return query

    def _breakdown(self, is_actors_query: bool):
        return Breakdown(
            team=self.team,
            query=self.query,
            series=self.series,
            query_date_range=self.query_date_range,
            timings=self.timings,
            modifiers=self.modifiers,
            events_filter=self._events_filter(
                breakdown=None,  # Passing in None because we know we dont actually need it
                ignore_breakdowns=True,
                is_actors_query=is_actors_query,
            ),
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
