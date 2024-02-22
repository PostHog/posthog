from typing import List, Optional, cast
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.aggregation_operations import (
    AggregationOperations,
)
from posthog.hogql_queries.insights.trends.breakdown import Breakdown
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.utils import series_event_name
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.action.action import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team
from posthog.schema import ActionsNode, EventsNode, HogQLQueryModifiers, TrendsQuery
from posthog.hogql_queries.insights.trends.trends_query_builder_abstract import TrendsQueryBuilderAbstract


class TrendsQueryBuilder(TrendsQueryBuilderAbstract):
    query: TrendsQuery
    team: Team
    query_date_range: QueryDateRange
    series: EventsNode | ActionsNode
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers

    def __init__(
        self,
        trends_query: TrendsQuery,
        team: Team,
        query_date_range: QueryDateRange,
        series: EventsNode | ActionsNode,
        timings: HogQLTimings,
        modifiers: HogQLQueryModifiers,
    ):
        self.query = trends_query
        self.team = team
        self.query_date_range = query_date_range
        self.series = series
        self.timings = timings
        self.modifiers = modifiers

    def build_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        breakdown = self._breakdown(is_actors_query=False)

        events_query: ast.SelectQuery | ast.SelectUnionQuery

        if self._trends_display.should_aggregate_values():
            events_query = self._get_events_subquery(False, is_actors_query=False, breakdown=breakdown)
        else:
            date_subqueries = self._get_date_subqueries(breakdown=breakdown)
            event_query = self._get_events_subquery(False, is_actors_query=False, breakdown=breakdown)

            events_query = ast.SelectUnionQuery(select_queries=[*date_subqueries, event_query])

        inner_select = self._inner_select_query(inner_query=events_query, breakdown=breakdown)
        full_query = self._outer_select_query(inner_query=inner_select, breakdown=breakdown)

        return full_query

    def build_actors_query(
        self, time_frame: Optional[str | int] = None, breakdown_filter: Optional[str | int] = None
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        breakdown = self._breakdown(is_actors_query=True, breakdown_values_override=breakdown_filter)

        return parse_select(
            """
                SELECT DISTINCT actor_id
                FROM {subquery}
            """,
            placeholders={
                "subquery": self._get_events_subquery(
                    False,
                    is_actors_query=True,
                    breakdown=breakdown,
                    breakdown_values_override=breakdown_filter,
                    actors_query_time_frame=time_frame,
                )
            },
        )

    def _get_date_subqueries(self, breakdown: Breakdown, ignore_breakdowns: bool = False) -> List[ast.SelectQuery]:
        if not breakdown.enabled or ignore_breakdowns:
            return [
                cast(
                    ast.SelectQuery,
                    parse_select(
                        """
                        SELECT
                            0 AS total,
                            {date_to_start_of_interval} - {number_interval_period} AS day_start
                        FROM
                            numbers(
                                coalesce(dateDiff({interval}, {date_from}, {date_to}), 0)
                            )
                    """,
                        placeholders={
                            **self.query_date_range.to_placeholders(),
                        },
                    ),
                ),
                cast(
                    ast.SelectQuery,
                    parse_select(
                        """
                        SELECT
                            0 AS total,
                            {date_from_start_of_interval} AS day_start
                    """,
                        placeholders={
                            **self.query_date_range.to_placeholders(),
                        },
                    ),
                ),
            ]

        return [
            cast(
                ast.SelectQuery,
                parse_select(
                    """
                    SELECT
                        0 AS total,
                        ticks.day_start as day_start,
                        breakdown_value
                    FROM (
                        SELECT
                            {date_to_start_of_interval} - {number_interval_period} AS day_start
                        FROM
                            numbers(
                                coalesce(dateDiff({interval}, {date_from}, {date_to}), 0)
                            )
                        UNION ALL
                        SELECT {date_from_start_of_interval} AS day_start
                    ) as ticks
                    CROSS JOIN (
                        SELECT breakdown_value
                        FROM (
                            SELECT {cross_join_breakdown_values}
                        )
                        ARRAY JOIN breakdown_value as breakdown_value
                    ) as sec
                    ORDER BY breakdown_value, day_start
                """,
                    placeholders={
                        **self.query_date_range.to_placeholders(),
                        **breakdown.placeholders(),
                    },
                ),
            )
        ]

    def _get_events_subquery(
        self,
        no_modifications: Optional[bool],
        is_actors_query: bool,
        breakdown: Breakdown,
        breakdown_values_override: Optional[str | int] = None,
        actors_query_time_frame: Optional[str | int] = None,
    ) -> ast.SelectQuery:
        day_start = ast.Alias(
            alias="day_start",
            expr=ast.Call(
                name=f"toStartOf{self.query_date_range.interval_name.title()}", args=[ast.Field(chain=["timestamp"])]
            ),
        )

        events_filter = self._events_filter(
            ignore_breakdowns=False,
            breakdown=breakdown,
            is_actors_query=is_actors_query,
            breakdown_values_override=breakdown_values_override,
            actors_query_time_frame=actors_query_time_frame,
        )

        default_query = cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    {aggregation_operation} AS total
                FROM events AS e
                SAMPLE {sample}
                WHERE {events_filter}
            """,
                placeholders={
                    "events_filter": events_filter,
                    "aggregation_operation": self._aggregation_operation.select_aggregation(),
                    "sample": self._sample_value(),
                },
            ),
        )

        default_query.group_by = []

        if not self._trends_display.should_aggregate_values() and not is_actors_query:
            default_query.select.append(day_start)
            default_query.group_by.append(ast.Field(chain=["day_start"]))

        # TODO: Move this logic into the below branches when working on adding breakdown support for the person modal
        if is_actors_query:
            default_query.select = [ast.Alias(alias="actor_id", expr=self._aggregation_operation.actor_id())]
            default_query.distinct = True
            default_query.group_by = []

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

            if is_actors_query:
                orchestrator.events_query_builder.append_select(
                    ast.Alias(alias="actor_id", expr=self._aggregation_operation.actor_id())
                )
                orchestrator.inner_select_query_builder.append_select(ast.Field(chain=["actor_id"]))
                orchestrator.parent_select_query_builder.append_select(ast.Field(chain=["actor_id"]))
            else:
                orchestrator.events_query_builder.append_select(breakdown.column_expr())
                orchestrator.events_query_builder.append_group_by(ast.Field(chain=["breakdown_value"]))

                orchestrator.inner_select_query_builder.append_select(ast.Field(chain=["breakdown_value"]))
                orchestrator.inner_select_query_builder.append_group_by(ast.Field(chain=["breakdown_value"]))

                orchestrator.parent_select_query_builder.append_select(ast.Field(chain=["breakdown_value"]))

            if (
                self._aggregation_operation.should_aggregate_values
                and not self._aggregation_operation.is_count_per_actor_variant()
                and not is_actors_query
            ):
                orchestrator.parent_select_query_builder.append_group_by(ast.Field(chain=["breakdown_value"]))

            return orchestrator.build()
        # Breakdowns and session duration math property
        elif breakdown.enabled and self._aggregation_operation.aggregating_on_session_duration():
            default_query.select = [
                ast.Alias(
                    alias="session_duration", expr=ast.Call(name="any", args=[ast.Field(chain=["session", "duration"])])
                ),
                breakdown.column_expr(),
            ]

            default_query.group_by.extend([ast.Field(chain=["session", "id"]), ast.Field(chain=["breakdown_value"])])

            wrapper = self.session_duration_math_property_wrapper(default_query)
            assert wrapper.group_by is not None

            if not self._trends_display.should_aggregate_values() and not is_actors_query:
                default_query.select.append(day_start)
                default_query.group_by.append(ast.Field(chain=["day_start"]))

                wrapper.select.append(ast.Field(chain=["day_start"]))
                wrapper.group_by.append(ast.Field(chain=["day_start"]))

            if is_actors_query:
                default_query.select.append(ast.Alias(alias="actor_id", expr=self._aggregation_operation.actor_id()))
                wrapper.select.append(ast.Field(chain=["actor_id"]))
            else:
                wrapper.select.append(ast.Field(chain=["breakdown_value"]))
                wrapper.group_by.append(ast.Field(chain=["breakdown_value"]))

            return wrapper
        # Just breakdowns
        elif breakdown.enabled:
            if not is_actors_query:
                default_query.select.append(breakdown.column_expr())
                default_query.group_by.append(ast.Field(chain=["breakdown_value"]))
        # Just session duration math property
        elif self._aggregation_operation.aggregating_on_session_duration():
            default_query.select = [
                ast.Alias(
                    alias="session_duration", expr=ast.Call(name="any", args=[ast.Field(chain=["session", "duration"])])
                )
            ]
            default_query.group_by.append(ast.Field(chain=["session", "id"]))

            wrapper = self.session_duration_math_property_wrapper(default_query)

            if not self._trends_display.should_aggregate_values() and not is_actors_query:
                assert wrapper.group_by is not None

                default_query.select.append(day_start)
                default_query.group_by.append(ast.Field(chain=["day_start"]))

                wrapper.select.append(ast.Field(chain=["day_start"]))
                wrapper.group_by.append(ast.Field(chain=["day_start"]))

            if is_actors_query:
                default_query.select.append(ast.Alias(alias="actor_id", expr=self._aggregation_operation.actor_id()))
                wrapper.select.append(ast.Field(chain=["actor_id"]))

            return wrapper
        # Just complex series aggregation
        elif self._aggregation_operation.requires_query_orchestration():
            orchestrator = self._aggregation_operation.get_query_orchestrator(
                events_where_clause=events_filter,
                sample_value=self._sample_value(),
            )

            if is_actors_query:
                orchestrator.events_query_builder.append_select(
                    ast.Alias(alias="actor_id", expr=self._aggregation_operation.actor_id())
                )
                orchestrator.inner_select_query_builder.append_select(ast.Field(chain=["actor_id"]))
                orchestrator.parent_select_query_builder.append_select(ast.Field(chain=["actor_id"]))

            return orchestrator.build()

        return default_query

    def _outer_select_query(self, breakdown: Breakdown, inner_query: ast.SelectQuery) -> ast.SelectQuery:
        query = cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    groupArray(day_start) AS date,
                    groupArray(count) AS total
                FROM {inner_query}
            """,
                placeholders={"inner_query": inner_query},
            ),
        )

        query = self._trends_display.modify_outer_query(
            outer_query=query,
            inner_query=inner_query,
            dates_queries=ast.SelectUnionQuery(
                select_queries=self._get_date_subqueries(ignore_breakdowns=True, breakdown=breakdown)
            ),
        )

        query.order_by = [ast.OrderExpr(expr=ast.Call(name="sum", args=[ast.Field(chain=["count"])]), order="DESC")]

        if breakdown.enabled:
            query.select.append(
                ast.Alias(
                    alias="breakdown_value",
                    expr=ast.Call(
                        name="ifNull",
                        args=[
                            ast.Call(name="toString", args=[ast.Field(chain=["breakdown_value"])]),
                            ast.Constant(value=""),
                        ],
                    ),
                )
            )
            query.group_by = [ast.Field(chain=["breakdown_value"])]
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

        if (
            self.query.trendsFilter is not None
            and self.query.trendsFilter.smoothingIntervals is not None
            and self.query.trendsFilter.smoothingIntervals > 1
        ):
            rolling_average = ast.Alias(
                alias="count",
                expr=ast.Call(
                    name="floor",
                    args=[
                        ast.WindowFunction(
                            name="avg",
                            args=[ast.Call(name="sum", args=[ast.Field(chain=["total"])])],
                            over_expr=ast.WindowExpr(
                                order_by=[ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC")],
                                frame_method="ROWS",
                                frame_start=ast.WindowFrameExpr(
                                    frame_type="PRECEDING",
                                    frame_value=int(self.query.trendsFilter.smoothingIntervals - 1),
                                ),
                                frame_end=ast.WindowFrameExpr(frame_type="CURRENT ROW"),
                            ),
                        )
                    ],
                ),
            )
            query.select = [rolling_average]

        query.group_by = []
        query.order_by = []

        if not self._trends_display.should_aggregate_values():
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
        actors_query_time_frame: Optional[str | int] = None,
    ) -> ast.Expr:
        series = self.series
        filters: List[ast.Expr] = []

        # Dates
        if is_actors_query and actors_query_time_frame is not None:
            to_start_of_time_frame = f"toStartOf{self.query_date_range.interval_name.capitalize()}"
            filters.append(
                ast.CompareOperation(
                    left=ast.Call(name=to_start_of_time_frame, args=[ast.Field(chain=["timestamp"])]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Call(name="toDateTime", args=[ast.Constant(value=actors_query_time_frame)]),
                )
            )
        elif not self._aggregation_operation.requires_query_orchestration():
            filters.extend(
                [
                    parse_expr(
                        "timestamp >= {date_from_with_adjusted_start_of_interval}",
                        placeholders=self.query_date_range.to_placeholders(),
                    ),
                    parse_expr(
                        "timestamp <= {date_to}",
                        placeholders=self.query_date_range.to_placeholders(),
                    ),
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

    def _breakdown(self, is_actors_query: bool, breakdown_values_override: Optional[str | int] = None):
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
        )

    @cached_property
    def _aggregation_operation(self) -> AggregationOperations:
        return AggregationOperations(
            self.team, self.series, self.query_date_range, self._trends_display.should_aggregate_values()
        )

    @cached_property
    def _trends_display(self) -> TrendsDisplay:
        display = (
            self.query.trendsFilter.display
            if self.query.trendsFilter is not None and self.query.trendsFilter.display is not None
            else None
        )
        return TrendsDisplay(display)
