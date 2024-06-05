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
from posthog.hogql_queries.insights.trends.breakdown import Breakdown
from posthog.hogql_queries.insights.trends.breakdown_values import BREAKDOWN_OTHER_STRING_LABEL
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.utils import series_event_name
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.action.action import Action
from posthog.models.filters.mixins.utils import cached_property
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
            return events_query
        else:
            event_query = self._get_events_subquery(False, is_actors_query=False, breakdown=breakdown)

            inner_select = self._inner_select_query(inner_query=event_query, breakdown=breakdown)
            full_query = self._outer_select_query(inner_query=inner_select, breakdown=breakdown)

            return full_query

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
        breakdown_values_override: Optional[str | int] = None,
        actors_query_time_frame: Optional[str] = None,
    ) -> ast.SelectQuery:
        events_filter = self._events_filter(
            ignore_breakdowns=False,
            breakdown=breakdown,
            is_actors_query=is_actors_query,
            breakdown_values_override=breakdown_values_override,
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

        if not self._trends_display.is_total_value():  # TODO: remove: and not is_actors_query
            # For cumulative unique users or groups, we want to count each user or group once per query, not per day
            if (
                self.query.trends_filter
                and self.query.trends_filter.display == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE
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

    def _outer_select_query(self, breakdown: Breakdown, inner_query: ast.SelectQuery) -> ast.SelectQuery:
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

        if self._trends_display.display_type == ChartDisplayType.ActionsLineGraphCumulative:
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
            query.group_by = [ast.Field(chain=["breakdown_value"])]
            query.order_by.insert(
                0,
                cast(
                    ast.OrderExpr,
                    parse_expr(
                        "breakdown_value = {other} ? 2 : breakdown_value = {nil} ? 1 : 0",
                        placeholders={
                            "other": ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
                            "nil": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                        },
                    ),
                ),
            )
            query.order_by.append(ast.OrderExpr(expr=ast.Field(chain=["breakdown_value"]), order="ASC"))

        return query

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
        breakdown_values_override: Optional[str | int] = None,
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

    def _breakdown(self, is_actors_query: bool, breakdown_values_override: Optional[str] = None):
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
                breakdown_values_override=breakdown_values_override,
            ),
            breakdown_values_override=[breakdown_values_override] if breakdown_values_override is not None else None,
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
