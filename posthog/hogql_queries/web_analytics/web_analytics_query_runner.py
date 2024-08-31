import typing
from abc import ABC
from datetime import timedelta
from math import ceil
from typing import Optional, Union

from django.conf import settings
from django.core.cache import cache
from django.utils.timezone import datetime

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    EventPropertyFilter,
    WebTopClicksQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    PersonPropertyFilter,
    SamplingRate,
    SessionPropertyFilter,
    WebGoalsQuery,
)
from posthog.utils import generate_cache_key, get_safe_cache

WebQueryNode = Union[WebOverviewQuery, WebTopClicksQuery, WebStatsTableQuery, WebGoalsQuery]


class WebAnalyticsQueryRunner(QueryRunner, ABC):
    query: WebQueryNode
    query_type: type[WebQueryNode]

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
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

    def session_where(self, include_previous_period: Optional[bool] = None):
        properties = [
            parse_expr(
                "events.timestamp < {date_to} AND events.timestamp >= minus({date_from}, toIntervalHour(1))",
                placeholders={
                    "date_from": self.query_date_range.previous_period_date_from_as_hogql()
                    if include_previous_period
                    else self.query_date_range.date_from_as_hogql(),
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
        properties = [
            parse_expr(
                "min_timestamp >= {date_from}",
                placeholders={
                    "date_from": self.query_date_range.previous_period_date_from_as_hogql()
                    if include_previous_period
                    else self.query_date_range.date_from_as_hogql(),
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
                    "date_from": self.query_date_range.previous_period_date_from_as_hogql()
                    if include_previous_period
                    else self.query_date_range.date_from_as_hogql(),
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
                    "events.timestamp < {date_to}",
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

    def _unsample(self, n: Optional[int | float]):
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
    return [[mapper[i](data) if i in mapper else data for i, data in enumerate(row)] for row in results]
