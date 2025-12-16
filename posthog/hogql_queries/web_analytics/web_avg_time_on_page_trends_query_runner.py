from datetime import datetime
from typing import Any, Union
from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedWebAvgTimeOnPageTrendsQueryResponse,
    EventPropertyFilter,
    IntervalType,
    PersonPropertyFilter,
    ResolvedDateRangeResponse,
    WebAvgTimeOnPageTrendsItem,
    WebAvgTimeOnPageTrendsQuery,
    WebAvgTimeOnPageTrendsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import get_property_key, get_property_type, property_to_expr

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property


class WebAvgTimeOnPageTrendsQueryRunner(WebAnalyticsQueryRunner[WebAvgTimeOnPageTrendsQueryResponse]):
    query: WebAvgTimeOnPageTrendsQuery
    response: WebAvgTimeOnPageTrendsQueryResponse
    cached_response: CachedWebAvgTimeOnPageTrendsQueryResponse
    paginator: HogQLHasMorePaginator

    INTERVAL_TO_CLICKHOUSE_FUNCTION: dict[IntervalType, str] = {
        IntervalType.HOUR: "toStartOfHour",
        IntervalType.DAY: "toStartOfDay",
        IntervalType.WEEK: "toStartOfWeek",
        IntervalType.MONTH: "toStartOfMonth",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset if self.query.offset else None,
        )

    @cached_property
    def query_date_range(self):
        timezone_info = (
            ZoneInfo("UTC")
            if self.modifiers and not self.modifiers.convertToProjectTimezone
            else self.team.timezone_info
        )
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            timezone_info=timezone_info,
            interval=self.query.interval,
            now=datetime.now(timezone_info),
        )

    def _get_interval_function(self) -> str:
        return self.INTERVAL_TO_CLICKHOUSE_FUNCTION.get(self.query.interval, "toStartOfDay")

    @cached_property
    def _event_properties_expr(self) -> ast.Expr:
        def map_pathname_property(prop: Union[EventPropertyFilter, PersonPropertyFilter]):
            if get_property_type(prop) == "event" and get_property_key(prop) == "$pathname":
                return EventPropertyFilter(
                    key="$prev_pageview_pathname",
                    operator=prop.operator,
                    value=prop.value,
                    label=prop.label,
                )
            return prop

        properties = [
            map_pathname_property(p)
            for p in self.query.properties + self._test_account_filters
            if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    @cached_property
    def _session_properties_expr(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    @cached_property
    def _bucket_expr(self) -> ast.Call:
        interval_function = self._get_interval_function()
        return ast.Call(
            name=interval_function,
            args=[ast.Field(chain=["timestamp"])],
        )

    def _build_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                bucket,
                avg(avg_time) AS avg_time_on_page
            FROM (
                SELECT
                    {bucket_expr} AS bucket,
                    avg(toFloat(events.properties.`$prev_pageview_duration`)) AS avg_time,
                    session.session_id AS session_id
                FROM events
                WHERE and(
                    or(events.event = '$pageview', events.event = '$pageleave', events.event = '$screen'),
                    events.properties.`$prev_pageview_duration` IS NOT NULL,
                    {date_range_filter},
                    {event_properties},
                    {session_properties}
                )
                GROUP BY session_id, bucket
            )
            GROUP BY bucket
            ORDER BY bucket
            """,
            timings=self.timings,
            placeholders={
                "bucket_expr": self._bucket_expr,
                "date_range_filter": self.events_where_data_range(),
                "event_properties": self._event_properties_expr,
                "session_properties": self._session_properties_expr,
            },
        )

    def _calculate(self) -> WebAvgTimeOnPageTrendsQueryResponse:
        response = self.paginator.execute_hogql_query(
            query_type="web_avg_time_on_page_trends_query",
            query=self._build_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = self._format_results(self.paginator.results or [])

        return WebAvgTimeOnPageTrendsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
            samplingRate=self._sample_rate,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
            **self.paginator.response_params(),
        )

    def _format_results(self, raw_results: list[Any]) -> list[WebAvgTimeOnPageTrendsItem]:
        return [
            WebAvgTimeOnPageTrendsItem(
                bucket=str(row[0]),
                avgTimeOnPage=float(row[1]) if row[1] is not None else 0.0,
            )
            for row in raw_results
        ]

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self._build_query()
