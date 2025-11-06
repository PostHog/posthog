import typing
from datetime import datetime
from functools import cached_property
from typing import Optional, cast

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta

from posthog.schema import (
    ActionsNode,
    BaseMathType,
    Compare,
    CompareFilter,
    DataWarehouseNode,
    EventsNode,
    HogQLQueryModifiers,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.insights.trends.aggregation_operations import (
    AggregationOperations,
    FirstTimeForUserEventsQueryAlternator,
)
from posthog.hogql_queries.insights.trends.breakdown import Breakdown
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.utils import is_groups_math
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models import Action, Team


class TrendsActorsQueryBuilder:
    trends_query: TrendsQuery
    team: Team
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext

    entity: EventsNode | ActionsNode
    time_frame: Optional[datetime]
    breakdown_value: Optional[str | int | list[str]] = None
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
        breakdown_value: Optional[str | int | list[str]] = None,
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

    @property
    def exact_timerange(self):
        return self.trends_query.dateRange and self.trends_query.dateRange.explicitDate

    @cached_property
    def trends_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.trends_query.dateRange,
            team=self.team,
            interval=self.trends_query.interval,
            now=datetime.now(),
            exact_timerange=self.exact_timerange,
        )

    @cached_property
    def trends_previous_date_range(self) -> QueryPreviousPeriodDateRange | QueryCompareToDateRange:
        if self.is_compare_to:
            return QueryCompareToDateRange(
                date_range=self.trends_query.dateRange,
                team=self.team,
                interval=self.trends_query.interval,
                now=datetime.now(),
                compare_to=typing.cast(str, typing.cast(CompareFilter, self.trends_query.compareFilter).compare_to),
                exact_timerange=self.exact_timerange,
            )
        return QueryPreviousPeriodDateRange(
            date_range=self.trends_query.dateRange,
            team=self.team,
            interval=self.trends_query.interval,
            now=datetime.now(),
            exact_timerange=self.exact_timerange,
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
            bool(self.trends_query.compareFilter and self.trends_query.compareFilter.compare)
            and self.compare_value == Compare.PREVIOUS
        )

    @cached_property
    def is_compare_to(self) -> bool:
        return (
            bool(self.trends_query.compareFilter and isinstance(self.trends_query.compareFilter.compare_to, str))
            and self.compare_value == Compare.PREVIOUS
        )

    @cached_property
    def is_active_users_math(self) -> bool:
        return self.trends_aggregation_operations.is_active_users_math()

    @cached_property
    def is_weekly_active_math(self) -> bool:
        return self.entity.math == BaseMathType.WEEKLY_ACTIVE

    @cached_property
    def is_monthly_active_math(self) -> bool:
        return self.entity.math == BaseMathType.MONTHLY_ACTIVE

    @cached_property
    def is_hourly(self) -> bool:
        return self.trends_date_range.is_hourly

    @cached_property
    def is_explicit(self) -> bool:
        return self.trends_date_range.explicit

    @cached_property
    def is_total_value(self) -> bool:
        return self.trends_display.is_total_value()

    def build_actors_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["actor_id"]),
                ast.Alias(alias="event_count", expr=self._get_actor_value_expr()),
                *self._get_event_distinct_ids_expr(),
                *self._get_matching_recordings_expr(),
            ],
            select_from=ast.JoinExpr(table=self._get_events_query()),
            group_by=[ast.Field(chain=["actor_id"])],
        )

    def _get_events_query(self) -> ast.SelectQuery:
        actor_col = ast.Alias(alias="actor_id", expr=self._actor_id_expr())
        actor_distinct_id_expr = self._actor_distinct_id_expr()
        actor_distinct_id_col = (
            ast.Alias(alias="distinct_id", expr=actor_distinct_id_expr) if actor_distinct_id_expr else None
        )
        columns: list[ast.Expr] = [
            ast.Alias(alias="uuid", expr=ast.Field(chain=["e", "uuid"])),
            *(
                [ast.Alias(alias="$session_id", expr=ast.Field(chain=["e", "$session_id"]))]
                if self.include_recordings
                else []
            ),
            *(
                [ast.Alias(alias="$window_id", expr=ast.Field(chain=["e", "$window_id"]))]
                if self.include_recordings
                else []
            ),
            *([actor_distinct_id_col] if actor_distinct_id_col else []),
        ]

        if self.trends_aggregation_operations.is_first_time_ever_math():
            date_from, date_to = self._date_where_expr()
            query_builder = FirstTimeForUserEventsQueryAlternator(
                ast.SelectQuery(select=[]),
                date_from,
                date_to,
                filters=self._events_where_expr(
                    with_date_range_expr=False, with_event_or_action_expr=False, with_breakdown_expr=False
                ),
                filters_with_breakdown=self._events_where_expr(
                    with_date_range_expr=False, with_event_or_action_expr=False
                ),
                event_or_action_filter=self._event_or_action_where_expr(),
                ratio=self._ratio_expr(),
                is_first_matching_event=self.trends_aggregation_operations.is_first_matching_event(),
            )
            query_builder.append_select(actor_col)
            query_builder.extend_select(columns, aggregate=True)
            query = cast(ast.SelectQuery, query_builder.build())
        else:
            query = ast.SelectQuery(
                select=[
                    actor_col,
                    ast.Alias(alias="timestamp", expr=ast.Field(chain=["e", "timestamp"])),
                    *columns,
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
        return [
            parse_expr(
                "groupUniqArray(100)(({timestamp}, uuid, $session_id, $window_id)) as matching_events",
                placeholders={
                    "timestamp": ast.Field(
                        chain=[
                            (
                                "timestamp"
                                if not self.trends_aggregation_operations.is_first_time_ever_math()
                                else "min_timestamp"
                            )
                        ]
                    )
                },
            )
        ]

    def _get_event_distinct_ids_expr(self) -> list[ast.Expr]:
        if is_groups_math(self.entity):
            return []

        return [
            ast.Alias(
                alias="event_distinct_ids",
                expr=ast.Call(name="groupUniqArray", args=[ast.Field(chain=["distinct_id"])]),
            )
        ]

    def _actor_id_expr(self) -> ast.Expr:
        if is_groups_math(self.entity):
            return ast.Field(chain=["e", f"$group_{int(cast(int, self.entity.math_group_type_index))}"])
        return ast.Field(chain=["e", "person_id"])

    def _actor_distinct_id_expr(self) -> ast.Expr | None:
        if is_groups_math(self.entity):
            return None
        return ast.Field(chain=["e", "distinct_id"])

    def _events_where_expr(
        self,
        with_breakdown_expr: bool = True,
        with_date_range_expr: bool = True,
        with_event_or_action_expr: bool = True,
    ) -> ast.And | None:
        exprs: list[ast.Expr] = [
            *self._entity_where_expr(),
            *self._prop_where_expr(),
            *(self._date_where_expr() if with_date_range_expr else []),
            *(self._breakdown_where_expr() if with_breakdown_expr else []),
            *self._filter_empty_actors_expr(),
        ]
        event_or_action_filter = self._event_or_action_where_expr()
        if with_event_or_action_expr and event_or_action_filter:
            exprs.append(event_or_action_filter)
        if exprs:
            return ast.And(exprs=exprs)
        return None

    def _ratio_expr(self) -> ast.RatioExpr | None:
        if self.trends_query.samplingFactor is None:
            return None
        return ast.RatioExpr(left=ast.Constant(value=self.trends_query.samplingFactor))

    def _sample_expr(self) -> ast.SampleExpr | None:
        sample_value = self._ratio_expr()
        if sample_value is None:
            return None
        return ast.SampleExpr(sample_value=sample_value)

    def _entity_where_expr(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []

        if self.entity.properties is not None and self.entity.properties != []:
            conditions.append(property_to_expr(self.entity.properties, self.team))

        return conditions

    def _event_or_action_where_expr(self) -> ast.Expr | None:
        if isinstance(self.entity, ActionsNode):
            # Actions
            try:
                action = Action.objects.get(pk=int(self.entity.id), team__project_id=self.team.project_id)
                return action_to_expr(action)
            except Action.DoesNotExist:
                # If an action doesn't exist, we want to return no events
                return parse_expr("1 = 2")
        elif isinstance(self.entity, EventsNode):
            if self.entity.event is not None:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=str(self.entity.event)),
                )

        else:
            raise ValueError(f"Invalid entity kind {self.entity.kind}")

        return None

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

    def _date_where_expr(self) -> tuple[ast.Expr, ast.Expr]:
        # types
        date_range: QueryDateRange | QueryCompareToDateRange | QueryPreviousPeriodDateRange
        if self.is_compare_previous:
            date_range = self.trends_previous_date_range
        else:
            date_range = self.trends_date_range

        query_from, query_to = date_range.date_from(), date_range.date_to()
        actors_from: datetime
        actors_from_expr: ast.Expr
        actors_to: datetime
        actors_to_expr: ast.Expr
        actors_to_op: ast.CompareOperationOp = ast.CompareOperationOp.Lt

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
                if self.is_compare_to:
                    self.time_frame = query_from + (self.time_frame - self.trends_date_range.date_from())
                else:
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

        return (
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
        )

    def _breakdown_where_expr(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []

        breakdown = Breakdown(
            team=self.team,
            query=self.trends_query,
            series=self.entity,
            query_date_range=self.trends_date_range,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        if self.breakdown_value is not None and breakdown.enabled:
            breakdown_filter = breakdown.get_actors_query_where_filter(lookup_values=self.breakdown_value)
            if breakdown_filter is not None:
                conditions.append(breakdown_filter)

        return conditions

    def _filter_empty_actors_expr(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []

        # Ignore empty groups
        if is_groups_math(self.entity):
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["e", f"$group_{int(cast(int, self.entity.math_group_type_index))}"]),
                    right=ast.Constant(value=""),
                )
            )

        return conditions
