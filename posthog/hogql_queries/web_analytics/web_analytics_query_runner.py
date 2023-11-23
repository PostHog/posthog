from abc import ABC
from datetime import timedelta
from math import ceil
from typing import Optional, List, Union, Type

from django.utils.timezone import datetime

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.caching.utils import is_stale
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    EventPropertyFilter,
    WebTopClicksQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    PersonPropertyFilter,
)

WebQueryNode = Union[WebOverviewQuery, WebTopClicksQuery, WebStatsTableQuery]


class WebAnalyticsQueryRunner(QueryRunner, ABC):
    query: WebQueryNode
    query_type: Type[WebQueryNode]

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
    def property_filters_without_pathname(self) -> List[Union[EventPropertyFilter, PersonPropertyFilter]]:
        return [p for p in self.query.properties if p.key != "$pathname"]

    def session_where(self, include_previous_period: Optional[bool] = None):
        properties = (
            [
                parse_expr(
                    "events.timestamp < {date_to} AND events.timestamp >= minus({date_from}, toIntervalHour(1))",
                    placeholders={
                        "date_from": self.query_date_range.previous_period_date_from_as_hogql()
                        if include_previous_period
                        else self.query_date_range.date_from_as_hogql(),
                        "date_to": self.query_date_range.date_to_as_hogql(),
                    },
                )
            ]
            + self.property_filters_without_pathname
            + self._test_account_filters
        )
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

    def events_where(self):
        properties = (
            [
                parse_expr(
                    "events.timestamp >= {date_from}",
                    placeholders={"date_from": self.query_date_range.date_from_as_hogql()},
                )
            ]
            + self.query.properties
            + self._test_account_filters
        )

        return property_to_expr(
            properties,
            self.team,
        )

    @cached_property
    def _test_account_filters(self):
        if isinstance(self.team.test_account_filters, list) and len(self.team.test_account_filters) > 0:
            return self.team.test_account_filters
        else:
            return []

    def _is_stale(self, cached_result_package):
        date_to = self.query_date_range.date_to()
        interval = self.query_date_range.interval_name
        return is_stale(self.team, date_to, interval, cached_result_package)

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
