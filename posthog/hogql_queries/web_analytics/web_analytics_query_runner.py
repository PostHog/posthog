import typing
from abc import ABC
from datetime import timedelta, datetime
from math import ceil
from typing import Optional, Union
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr, action_to_expr, apply_path_cleaning
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.hogql.database.schema.exchange_rate import revenue_where_expr_for_events

from posthog.models import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    ActionConversionGoal,
    CustomEventConversionGoal,
    EventPropertyFilter,
    WebOverviewQuery,
    WebPageURLSearchQuery,
    WebStatsTableQuery,
    PersonPropertyFilter,
    SamplingRate,
    SessionPropertyFilter,
    WebGoalsQuery,
    WebExternalClicksTableQuery,
    WebVitalsPathBreakdownQuery,
)
from posthog.utils import generate_cache_key, get_safe_cache

WebQueryNode = Union[
    WebOverviewQuery,
    WebStatsTableQuery,
    WebGoalsQuery,
    WebExternalClicksTableQuery,
    WebVitalsPathBreakdownQuery,
    WebPageURLSearchQuery,
]


class WebAnalyticsQueryRunner(QueryRunner, ABC):
    query: WebQueryNode
    query_type: type[WebQueryNode]

    @cached_property
    def query_date_range(self):
        # Respect the convertToProjectTimezone modifier for date range calculation
        # When convertToProjectTimezone=False, use UTC for both date boundaries AND column conversion
        timezone_info = (
            ZoneInfo("UTC")
            if self.modifiers and not self.modifiers.convertToProjectTimezone
            else self.team.timezone_info
        )
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            timezone_info=timezone_info,
            interval=None,
            now=datetime.now(timezone_info),
        )

    @cached_property
    def query_compare_to_date_range(self):
        if self.query.compareFilter is not None:
            if isinstance(self.query.compareFilter.compare_to, str):
                return QueryCompareToDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=None,
                    now=datetime.now(),
                    compare_to=self.query.compareFilter.compare_to,
                )
            elif self.query.compareFilter.compare:
                return QueryPreviousPeriodDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=None,
                    now=datetime.now(),
                )

        return None

    def _current_period_expression(self, field="start_timestamp"):
        return ast.Call(
            name="and",
            args=[
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_date_range.date_from_as_hogql(),
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_date_range.date_to_as_hogql(),
                    op=ast.CompareOperationOp.LtEq,
                ),
            ],
        )

    def _previous_period_expression(self, field="start_timestamp"):
        # NOTE: Returning `ast.Constant(value=None)` is painfully slow, make sure we return a boolean
        if not self.query_compare_to_date_range:
            return ast.Constant(value=False)

        return ast.Call(
            name="and",
            args=[
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_compare_to_date_range.date_from_as_hogql(),
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_compare_to_date_range.date_to_as_hogql(),
                    op=ast.CompareOperationOp.LtEq,
                ),
            ],
        )

    def _periods_expression(self, field="timestamp"):
        return ast.Call(
            name="or",
            args=[
                self._current_period_expression(field),
                self._previous_period_expression(field),
            ],
        )

    @cached_property
    def pathname_property_filter(self) -> Optional[EventPropertyFilter]:
        for p in self.query.properties:
            if isinstance(p, EventPropertyFilter) and p.key == "$pathname":
                return p
        return None

    @cached_property
    def property_filters_without_pathname(
        self,
    ) -> list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]:
        return [p for p in self.query.properties if p.key != "$pathname"]

    @cached_property
    def conversion_goal_expr(self) -> Optional[ast.Expr]:
        if isinstance(self.query.conversionGoal, ActionConversionGoal):
            action = Action.objects.get(pk=self.query.conversionGoal.actionId, team__project_id=self.team.project_id)
            return action_to_expr(action)
        elif isinstance(self.query.conversionGoal, CustomEventConversionGoal):
            return ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.query.conversionGoal.customEventName),
            )
        else:
            return None

    @cached_property
    def conversion_count_expr(self) -> Optional[ast.Expr]:
        if self.conversion_goal_expr:
            return ast.Call(name="countIf", args=[self.conversion_goal_expr])
        else:
            return None

    @cached_property
    def conversion_person_id_expr(self) -> Optional[ast.Expr]:
        if self.conversion_goal_expr:
            return ast.Call(
                name="any",
                args=[
                    ast.Call(
                        name="if",
                        args=[
                            self.conversion_goal_expr,
                            ast.Field(chain=["events", "person_id"]),
                            ast.Constant(value=None),
                        ],
                    )
                ],
            )
        else:
            return None

    @cached_property
    def conversion_revenue_expr(self) -> ast.Expr:
        if not self.team.revenue_analytics_config.events:
            return ast.Constant(value=None)

        if isinstance(self.query.conversionGoal, CustomEventConversionGoal):
            event_name = self.query.conversionGoal.customEventName
            revenue_property = next(
                (
                    event_item.revenueProperty
                    for event_item in self.team.revenue_analytics_config.events
                    if event_item.eventName == event_name
                ),
                None,
            )

            if not revenue_property:
                return ast.Constant(value=None)

            return ast.Call(
                name="sumIf",
                args=[
                    ast.Call(
                        name="ifNull",
                        args=[
                            ast.Call(
                                name="toFloat", args=[ast.Field(chain=["events", "properties", revenue_property])]
                            ),
                            ast.Constant(value=0),
                        ],
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value=event_name),
                    ),
                ],
            )
        else:
            # for now, don't support conversion revenue for actions
            return ast.Constant(value=None)

    @cached_property
    def event_type_expr(self) -> ast.Expr:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value="$pageview")
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value="$screen")
            ),
        ]

        if self.conversion_goal_expr:
            exprs.append(self.conversion_goal_expr)
        elif self.query.includeRevenue:
            # Use elif here, we don't need to include revenue events if we already included conversion events, because
            # if there is a conversion goal set then we only show revenue from conversion events.
            exprs.append(revenue_where_expr_for_events(self.team))

        return ast.Or(exprs=exprs)

    def period_aggregate(
        self,
        function_name: str,
        column_name: str,
        start: ast.Expr,
        end: ast.Expr,
        alias: Optional[str] = None,
        params: Optional[list[ast.Expr]] = None,
    ):
        expr = ast.Call(
            name=function_name + "If",
            params=params,
            args=[
                ast.Field(chain=[column_name]),
                ast.Call(
                    name="and",
                    args=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.GtEq,
                            left=ast.Field(chain=["start_timestamp"]),
                            right=start,
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.LtEq,
                            left=ast.Field(chain=["start_timestamp"]),
                            right=end,
                        ),
                    ],
                ),
            ],
        )

        if alias is not None:
            return ast.Alias(alias=alias, expr=expr)

        return expr

    def session_where(self, include_previous_period: Optional[bool] = None):
        properties = [
            parse_expr(
                "events.timestamp <= {date_to} AND events.timestamp >= minus({date_from}, toIntervalHour(1))",
                placeholders={
                    "date_from": (
                        self.query_date_range.previous_period_date_from_as_hogql()
                        if include_previous_period
                        else self.query_date_range.date_from_as_hogql()
                    ),
                    "date_to": self.query_date_range.date_to_as_hogql(),
                },
            ),
            *self.property_filters_without_pathname,
            *self._test_account_filters,
        ]
        return property_to_expr(
            properties,
            self.team,
        )

    def session_having(self, include_previous_period: Optional[bool] = None):
        properties: list[Union[ast.Expr, EventPropertyFilter]] = [
            parse_expr(
                "min_timestamp >= {date_from}",
                placeholders={
                    "date_from": (
                        self.query_date_range.previous_period_date_from_as_hogql()
                        if include_previous_period
                        else self.query_date_range.date_from_as_hogql()
                    ),
                },
            )
        ]
        pathname = self.pathname_property_filter
        if pathname:
            properties.append(
                EventPropertyFilter(
                    key="session_initial_pathname",
                    label=pathname.label,
                    operator=pathname.operator,
                    value=pathname.value,
                )
            )
        return property_to_expr(
            properties,
            self.team,
        )

    def sessions_table_properties(self, include_previous_period: Optional[bool] = None):
        properties = [
            parse_expr(
                "sessions.min_timestamp >= {date_from}",
                placeholders={
                    "date_from": (
                        self.query_date_range.previous_period_date_from_as_hogql()
                        if include_previous_period
                        else self.query_date_range.date_from_as_hogql()
                    ),
                },
            )
        ]
        return property_to_expr(
            properties,
            self.team,
        )

    def events_where(self):
        properties = [self.events_where_data_range(), self.query.properties, self._test_account_filters]

        return property_to_expr(
            properties,
            self.team,
        )

    def events_where_data_range(self):
        return property_to_expr(
            [
                parse_expr(
                    "events.timestamp >= {date_from}",
                    placeholders={"date_from": self.query_date_range.date_from_as_hogql()},
                ),
                parse_expr(
                    "events.timestamp <= {date_to}",
                    placeholders={"date_to": self.query_date_range.date_to_as_hogql()},
                ),
            ],
            self.team,
        )

    @cached_property
    def _test_account_filters(self):
        if not self.query.filterTestAccounts:
            return []
        if isinstance(self.team.test_account_filters, list) and len(self.team.test_account_filters) > 0:
            return self.team.test_account_filters
        else:
            return []

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

    def _sample_rate_cache_key(self) -> str:
        return generate_cache_key(
            f"web_analytics_sample_rate_{self.query.dateRange.model_dump_json() if self.query.dateRange else None}_{self.team.pk}_{self.team.timezone}"
        )

    def _get_or_calculate_sample_ratio(self) -> SamplingRate:
        if not self.query.sampling or not self.query.sampling.enabled:
            return SamplingRate(numerator=1)
        if self.query.sampling.forceSamplingRate:
            return self.query.sampling.forceSamplingRate

        cache_key = self._sample_rate_cache_key()
        cached_response = get_safe_cache(cache_key)
        if cached_response:
            return SamplingRate(**cached_response)

        # To get the sample rate, we need to count how many page view events there were over the time period.
        # This would be quite slow if there were a lot of events, so use sampling to calculate this!

        with self.timings.measure("event_count_query"):
            event_count = parse_select(
                """
SELECT
    count() as count
FROM
    events
SAMPLE 1/1000
WHERE
    {where}
                """,
                timings=self.timings,
                placeholders={
                    "where": self.events_where_data_range(),
                },
            )

        with self.timings.measure("event_count_query_execute"):
            response = execute_hogql_query(
                query_type="event_count_query",
                query=event_count,
                team=self.team,
                timings=self.timings,
                limit_context=self.limit_context,
            )

        if not response.results or not response.results[0] or not response.results[0][0]:
            return SamplingRate(numerator=1)

        count = response.results[0][0] * 1000
        fresh_sample_rate = _sample_rate_from_count(count)

        cache.set(cache_key, fresh_sample_rate, settings.CACHED_RESULTS_TTL)

        return fresh_sample_rate

    @cached_property
    def _sample_rate(self) -> SamplingRate:
        return self._get_or_calculate_sample_ratio()

    @cached_property
    def _sample_ratio(self) -> ast.RatioExpr:
        sample_rate = self._sample_rate
        return ast.RatioExpr(
            left=ast.Constant(value=sample_rate.numerator),
            right=ast.Constant(value=sample_rate.denominator) if sample_rate.denominator else None,
        )

    def _apply_path_cleaning(self, path_expr: ast.Expr) -> ast.Expr:
        if not self.query.doPathCleaning:
            return path_expr

        return apply_path_cleaning(path_expr, self.team)

    def _unsample(self, n: Optional[int | float], _row: Optional[list[int | float]] = None):
        if n is None:
            return None

        return (
            n * self._sample_rate.denominator / self._sample_rate.numerator
            if self._sample_rate.denominator
            else n / self._sample_rate.numerator
        )

    def get_cache_key(self) -> str:
        original = super().get_cache_key()
        return f"{original}_{self.team.path_cleaning_filters}"

    @cached_property
    def events_session_property(self):
        # we should delete this once SessionsV2JoinMode is always uuid, eventually we will always use $session_id_uuid
        if self.query.modifiers and self.query.modifiers.sessionsV2JoinMode == "uuid":
            return parse_expr("events.$session_id_uuid")
        else:
            return parse_expr("events.$session_id")


def _sample_rate_from_count(count: int) -> SamplingRate:
    # Change the sample rate so that the query will sample about 100_000 to 1_000_000 events, but use defined steps of
    # sample rate. These numbers are just a starting point, and we can tune as we get feedback.
    sample_target = 10_000
    sample_rate_steps = [1_000, 100, 10]

    for step in sample_rate_steps:
        if count / sample_target >= step:
            return SamplingRate(numerator=1, denominator=step)
    return SamplingRate(numerator=1)


def map_columns(results, mapper: dict[int, typing.Callable]):
    return [[mapper[i](data, row) if i in mapper else data for i, data in enumerate(row)] for row in results]
