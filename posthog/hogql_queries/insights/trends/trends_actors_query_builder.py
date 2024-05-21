from datetime import datetime
from functools import cached_property
from typing import Optional

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.aggregation_operations import AggregationOperations
from posthog.hogql_queries.insights.trends.breakdown import Breakdown
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models import Action, Team
from posthog.schema import (
    ActionsNode,
    BaseMathType,
    Compare,
    DataWarehouseNode,
    EventsNode,
    HogQLQueryModifiers,
    TrendsFilter,
    TrendsQuery,
)


class TrendsActorsQueryBuilder:
    trends_query: TrendsQuery
    team: Team
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext

    entity: EventsNode | ActionsNode
    time_frame: Optional[datetime]
    breakdown_value: Optional[str | int] = None
    compare_value: Optional[Compare] = None
    include_recordings: Optional[bool] = None

    def __init__(
        self,
        trends_query: TrendsQuery,
        team: Team,
        timings: HogQLTimings,
        modifiers: HogQLQueryModifiers,
        series_index: int,
        time_frame: Optional[str | datetime],
        breakdown_value: Optional[str | int] = None,
        compare_value: Optional[Compare] = None,
        include_recordings: Optional[bool] = None,
        limit_context: LimitContext = LimitContext.QUERY,
    ):
        self.trends_query = trends_query
        self.team = team
        self.timings = timings
        self.modifiers = modifiers
        self.limit_context = limit_context

        entity = trends_query.series[series_index]

        # TODO: Add support for DataWarehouseNode
        if isinstance(entity, DataWarehouseNode):
            raise Exception("DataWarehouseNodes are not supported for trends actors queries")
        else:
            self.entity = entity

        if time_frame is None or isinstance(time_frame, datetime):
            self.time_frame = time_frame
        else:
            parsed_time_frame = parse(time_frame)

            if parsed_time_frame.tzinfo is None:
                parsed_time_frame = parsed_time_frame.replace(tzinfo=self.team.timezone_info)

            self.time_frame = parsed_time_frame

        self.breakdown_value = breakdown_value
        self.compare_value = compare_value
        self.include_recordings = include_recordings

    @cached_property
    def trends_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.trends_query.dateRange,
            team=self.team,
            interval=self.trends_query.interval,
            now=datetime.now(),
        )

    @cached_property
    def trends_previous_date_range(self) -> QueryPreviousPeriodDateRange:
        return QueryPreviousPeriodDateRange(
            date_range=self.trends_query.dateRange,
            team=self.team,
            interval=self.trends_query.interval,
            now=datetime.now(),
        )

    @cached_property
    def trends_display(self) -> TrendsDisplay:
        trends_filter = self.trends_query.trendsFilter or TrendsFilter()
        return TrendsDisplay(trends_filter.display)

    @cached_property
    def trends_aggregation_operations(self) -> AggregationOperations:
        return AggregationOperations(
            self.team,
            self.entity,
            self.trends_display.display_type,
            self.trends_date_range,  # TODO: does this need to be adjusted for compare queries?
            self.trends_display.is_total_value(),
        )

    @cached_property
    def is_compare_previous(self) -> bool:
        return (
            bool(self.trends_query.trendsFilter and self.trends_query.trendsFilter.compare)
            and self.compare_value == Compare.previous
        )

    @cached_property
    def is_active_users_math(self) -> bool:
        return self.trends_aggregation_operations.is_active_users_math()

    @cached_property
    def is_weekly_active_math(self) -> bool:
        return self.entity.math == BaseMathType.weekly_active

    @cached_property
    def is_monthly_active_math(self) -> bool:
        return self.entity.math == BaseMathType.monthly_active

    @cached_property
    def is_hourly(self) -> bool:
        return self.trends_date_range.is_hourly

    @cached_property
    def is_explicit(self) -> bool:
        return self.trends_date_range.explicit

    @cached_property
    def is_total_value(self) -> bool:
        return self.trends_display.is_total_value()

    def build_actors_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["actor_id"]),
                ast.Alias(alias="event_count", expr=self._get_actor_value_expr()),
                *self._get_matching_recordings_expr(),
            ],
            select_from=ast.JoinExpr(table=self._get_events_query()),
            group_by=[ast.Field(chain=["actor_id"])],
        )

    def _get_events_query(self) -> ast.SelectQuery:
        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="actor_id", expr=self._actor_id_expr()),
                ast.Field(chain=["e", "timestamp"]),
                ast.Field(chain=["e", "uuid"]),
                *([ast.Field(chain=["e", "$session_id"])] if self.include_recordings else []),
                *([ast.Field(chain=["e", "$window_id"])] if self.include_recordings else []),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                alias="e",
                sample=self._sample_expr(),
            ),
            where=self._events_where_expr(),
        )
        return query

    def _get_actor_value_expr(self) -> ast.Expr:
        return parse_expr("count()")

    def _get_matching_recordings_expr(self) -> list[ast.Expr]:
        if not self.include_recordings:
            return []
        return [parse_expr("groupUniqArray(100)((timestamp, uuid, $session_id, $window_id)) as matching_events")]

    def _actor_id_expr(self) -> ast.Expr:
        if self.entity.math == "unique_group" and self.entity.math_group_type_index is not None:
            return ast.Field(chain=["e", f"$group_{int(self.entity.math_group_type_index)}"])
        return ast.Field(chain=["e", "person_id"])

    def _events_where_expr(self, with_breakdown_expr: bool = True) -> ast.And:
        return ast.And(
            exprs=[
                *self._entity_where_expr(),
                *self._prop_where_expr(),
                *self._date_where_expr(),
                *(self._breakdown_where_expr() if with_breakdown_expr else []),
                *self._filter_empty_actors_expr(),
            ]
        )

    def _sample_expr(self) -> ast.SampleExpr | None:
        if self.trends_query.samplingFactor is None:
            return None

        return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=self.trends_query.samplingFactor)))

    def _entity_where_expr(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []

        if isinstance(self.entity, ActionsNode):
            # Actions
            try:
                action = Action.objects.get(pk=int(self.entity.id), team=self.team)
                conditions.append(action_to_expr(action))
            except Action.DoesNotExist:
                # If an action doesn't exist, we want to return no events
                conditions.append(parse_expr("1 = 2"))
        elif isinstance(self.entity, EventsNode):
            if self.entity.event is not None:
                conditions.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value=str(self.entity.event)),
                    )
                )

            if self.entity.properties is not None and self.entity.properties != []:
                conditions.append(property_to_expr(self.entity.properties, self.team))
        else:
            raise ValueError(f"Invalid entity kind {self.entity.kind}")

        return conditions

    def _prop_where_expr(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []

        # Filter Test Accounts
        if (
            self.trends_query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for property in self.team.test_account_filters:
                conditions.append(property_to_expr(property, self.team))

        # Properties
        if self.trends_query.properties is not None and self.trends_query.properties != []:
            conditions.append(property_to_expr(self.trends_query.properties, self.team))

        return conditions

    def _date_where_expr(self) -> list[ast.Expr]:
        # types
        date_range: QueryDateRange = (
            self.trends_previous_date_range if self.is_compare_previous else self.trends_date_range
        )
        query_from, query_to = date_range.date_from(), date_range.date_to()
        actors_from: datetime
        actors_from_expr: ast.Expr
        actors_to: datetime
        actors_to_expr: ast.Expr
        actors_to_op: ast.CompareOperationOp = ast.CompareOperationOp.Lt

        conditions: list[ast.Expr] = []

        if self.is_total_value:
            assert (
                self.time_frame is None
            ), "A `day` is forbidden for trends actors queries with total value aggregation"

            actors_from = query_from
            actors_to = query_to
            actors_to_op = ast.CompareOperationOp.LtEq
        else:
            assert (
                self.time_frame is not None
            ), "A `day` is required for trends actors queries without total value aggregation"

            # use previous day/week/... for time_frame
            if self.is_compare_previous:
                relative_delta = relativedelta(**date_range.date_from_delta_mappings())  # type: ignore
                previous_time_frame = self.time_frame - relative_delta
                if self.is_hourly:
                    self.time_frame = previous_time_frame
                else:
                    self.time_frame = previous_time_frame.replace(hour=0, minute=0, second=0, microsecond=0)

            actors_from = self.time_frame
            actors_to = actors_from + date_range.interval_relativedelta()

            # exclude events before the query start and after the query end
            if self.is_explicit and not self.is_active_users_math:
                if query_from > actors_from:
                    actors_from = query_from

                if query_to < actors_to:
                    actors_to_op = ast.CompareOperationOp.LtEq
                    actors_to = query_to

        # adjust date_from for weekly and monthly active calculations
        if self.is_active_users_math:
            if self.is_total_value:
                # TRICKY: On total value (non-time-series) insights, WAU/MAU math is simply meaningless.
                # There's no intuitive way to define the semantics of such a combination, so what we do is just turn it
                # into a count of unique users between `date_to - INTERVAL (7|30) DAY` and `date_to`.
                # This way we at least ensure the date range is the probably expected 7 or 30 days.
                actors_from = actors_to

            if self.is_weekly_active_math:
                actors_from_expr = ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub,
                    left=ast.Constant(value=actors_from),
                    right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=6)]),
                )
                actors_to_expr = ast.Constant(value=actors_to)
            elif self.is_monthly_active_math:
                actors_from_expr = ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub,
                    left=ast.Constant(value=actors_from),
                    right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=29)]),
                )
                actors_to_expr = ast.Constant(value=actors_to)

            if self.is_explicit:
                actors_from_expr = ast.Call(name="greatest", args=[actors_from_expr, ast.Constant(value=query_from)])
                actors_to_expr = ast.Call(
                    name="least", args=[ast.Constant(value=actors_to), ast.Constant(value=query_to)]
                )
        else:
            actors_from_expr = ast.Constant(value=actors_from)
            actors_to_expr = ast.Constant(value=actors_to)

        conditions.extend(
            [
                ast.CompareOperation(
                    left=ast.Field(chain=["timestamp"]),
                    op=ast.CompareOperationOp.GtEq,
                    right=actors_from_expr,
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["timestamp"]),
                    op=actors_to_op,
                    right=actors_to_expr,
                ),
            ]
        )

        return conditions

    def _breakdown_where_expr(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []

        breakdown = Breakdown(
            team=self.team,
            query=self.trends_query,
            series=self.entity,
            query_date_range=self.trends_date_range,
            timings=self.timings,
            modifiers=self.modifiers,
            events_filter=self._events_where_expr(with_breakdown_expr=False),
            breakdown_values_override=[str(self.breakdown_value)] if self.breakdown_value is not None else None,
            limit_context=self.limit_context,
        )

        if breakdown.enabled and not breakdown.is_histogram_breakdown:
            breakdown_filter = breakdown.events_where_filter()
            if breakdown_filter is not None:
                conditions.append(breakdown_filter)

        return conditions

    def _filter_empty_actors_expr(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []

        # Ignore empty groups
        if self.entity.math == "unique_group" and self.entity.math_group_type_index is not None:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["e", f"$group_{int(self.entity.math_group_type_index)}"]),
                    right=ast.Constant(value=""),
                )
            )

        return conditions
