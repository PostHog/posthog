import typing
from abc import ABC
from datetime import datetime, timedelta
from math import ceil
from typing import Optional, Union
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache

from posthog.schema import (
    ActionConversionGoal,
    CustomEventConversionGoal,
    EventPropertyFilter,
    PersonPropertyFilter,
    SamplingRate,
    SessionPropertyFilter,
    WebExternalClicksTableQuery,
    WebGoalsQuery,
    WebOverviewQuery,
    WebPageURLSearchQuery,
    WebStatsTableQuery,
    WebTrendsQuery,
    WebVitalsPathBreakdownQuery,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import action_to_expr, apply_path_cleaning, property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.hogql_queries.query_runner import AnalyticsQueryResponseProtocol, AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models import Action, User
from posthog.models.filters.mixins.utils import cached_property
from posthog.rbac.user_access_control import UserAccessControl
from posthog.utils import generate_cache_key, get_safe_cache

WebQueryNode = Union[
    WebOverviewQuery,
    WebStatsTableQuery,
    WebGoalsQuery,
    WebExternalClicksTableQuery,
    WebVitalsPathBreakdownQuery,
    WebPageURLSearchQuery,
    WebTrendsQuery,
]

WAR = typing.TypeVar("WAR", bound=AnalyticsQueryResponseProtocol)


class WebAnalyticsQueryRunner(AnalyticsQueryRunner[WAR], ABC):
    query: WebQueryNode
    query_type: type[WebQueryNode]

    def validate_query_runner_access(self, user: User) -> bool:
        user_access_control = UserAccessControl(user=user, team=self.team)
        return user_access_control.assert_access_level_for_resource("web_analytics", "viewer")

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
    def configured_event_types(self) -> list[str]:
        event_types = self.team.web_analytics_event_types
        if not event_types:
            return ["$pageview", "$screen"]
        return event_types

    @cached_property
    def event_type_expr(self) -> ast.Expr:
        exprs: list[ast.Expr] = []

        for event_type in self.configured_event_types:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=event_type),
                )
            )

        if self.conversion_goal_expr:
            exprs.append(self.conversion_goal_expr)

        if len(exprs) == 1:
            return exprs[0]
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

    @cached_property
    def session_expansion_enabled(self) -> bool:
        expansion_enabled = self.team.web_analytics_session_expansion_enabled
        # Default to True (current behavior) if not explicitly set
        return expansion_enabled is None or expansion_enabled is True

    def session_where(self, include_previous_period: Optional[bool] = None):
        # When session expansion is enabled, expand the timestamp filter by 1 hour backward
        # to capture sessions that started before the date range but have events within it.
        # When disabled, use strict date boundaries like Product Analytics.
        if self.session_expansion_enabled:
            timestamp_expr = (
                "events.timestamp <= {date_to} AND events.timestamp >= minus({date_from}, toIntervalHour(1))"
            )
        else:
            timestamp_expr = "events.timestamp <= {date_to} AND events.timestamp >= {date_from}"

        properties = [
            parse_expr(
                timestamp_expr,
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
        properties: list[Union[ast.Expr, EventPropertyFilter]] = []

        # Only apply the min_timestamp filter when session expansion is enabled.
        # This filters out sessions that started too early (before the expanded window).
        # When expansion is disabled, we use strict date boundaries in session_where instead.
        if self.session_expansion_enabled:
            properties.append(
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
            )

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

        if not properties:
            return ast.Constant(value=True)

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
            self.team.pk,
            f"web_analytics_sample_rate_{self.query.dateRange.model_dump_json() if self.query.dateRange else None}_{self.team.pk}_{self.team.timezone}",
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
