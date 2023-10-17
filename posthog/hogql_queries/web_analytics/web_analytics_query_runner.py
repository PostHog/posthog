from abc import ABC
from typing import Optional, List, Union, Type

from django.utils.timezone import datetime
from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    EventPropertyFilter,
    WebTopClicksQuery,
    WebOverviewStatsQuery,
    WebStatsTableQuery,
    HogQLPropertyFilter,
)

WebQueryNode = Union[
    WebOverviewStatsQuery,
    WebTopClicksQuery,
    WebStatsTableQuery,
]


class WebAnalyticsQueryRunner(QueryRunner, ABC):
    query: WebQueryNode
    query_type: Type[WebQueryNode]

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL

    @cached_property
    def query_date_range(self):
        return QueryDateRange(date_range=self.query.dateRange, team=self.team, interval=None, now=datetime.now())

    @cached_property
    def pathname_property_filter(self) -> Optional[EventPropertyFilter]:
        for p in self.query.properties:
            if isinstance(p, EventPropertyFilter) and p.key == "$pathname":
                return p
        return None

    @cached_property
    def property_filters_without_pathname(self) -> List[Union[EventPropertyFilter, HogQLPropertyFilter]]:
        return [p for p in self.query.properties if p.key != "$pathname"]

    def session_where(self):
        properties = [
            parse_expr(
                "events.timestamp < {date_to} AND events.timestamp >= minus({date_from}, toIntervalHour(1))",
                placeholders={
                    "date_from": self.query_date_range.date_from_as_hogql(),
                    "date_to": self.query_date_range.date_to_as_hogql(),
                },
            )
        ] + self.property_filters_without_pathname
        return property_to_expr(
            properties,
            self.team,
        )

    def session_having(self):
        properties = [
            parse_expr(
                "min_timestamp >= {date_from}",
                placeholders={"date_from": self.query_date_range.date_from_as_hogql()},
            )
        ]
        pathname = self.pathname_property_filter
        if pathname:
            properties.append(
                EventPropertyFilter(
                    key="earliest_pathname", label=pathname.label, operator=pathname.operator, value=pathname.value
                )
            )
        return property_to_expr(
            properties,
            self.team,
        )

    def events_where(self):
        properties = [
            parse_expr(
                "events.timestamp >= {date_from}",
                placeholders={"date_from": self.query_date_range.date_from_as_hogql()},
            )
        ] + self.query.properties
        return property_to_expr(
            properties,
            self.team,
        )
