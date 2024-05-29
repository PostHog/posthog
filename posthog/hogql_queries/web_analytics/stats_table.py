from typing import Union

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql.property import (
    property_to_expr,
    get_property_operator,
    get_property_value,
    get_property_type,
    get_property_key,
)
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
    map_columns,
)
from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    WebStatsTableQuery,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
    EventPropertyFilter,
    PersonPropertyFilter,
)


class WebStatsTableQueryRunner(WebAnalyticsQueryRunner):
    query: WebStatsTableQuery
    response: WebStatsTableQueryResponse
    cached_response: CachedWebStatsTableQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

    def to_query(self) -> ast.SelectQuery:
        if self.query.breakdownBy == WebStatsBreakdown.Page:
            if self.query.includeScrollDepth and self.query.includeBounceRate:
                return self.to_path_scroll_bounce_query()
            elif self.query.includeBounceRate:
                return self.to_path_bounce_query()
        if self.query.breakdownBy == WebStatsBreakdown.InitialPage:
            if self.query.includeBounceRate:
                return self.to_entry_bounce_query()
        if self._has_session_properties():
            return self._to_main_query_with_session_properties()
        return self.to_main_query()

    def to_main_query(self) -> ast.SelectQuery:
        with self.timings.measure("stats_table_query"):
            query = parse_select(
                """
SELECT
    breakdown_value AS "context.columns.breakdown_value",
    count(person_id) AS "context.columns.visitors",
    sum(filtered_pageview_count) AS "context.columns.views"
FROM (
    SELECT
        any(person_id) AS person_id,
        count() AS filtered_pageview_count,
        {breakdown_value} AS breakdown_value
    FROM events
    WHERE and(
        timestamp >= {date_from},
        timestamp < {date_to},
        events.event == '$pageview',
        {all_properties},
        {where_breakdown}
    )
    GROUP BY events.`$session_id`, breakdown_value
)
GROUP BY "context.columns.breakdown_value"
ORDER BY "context.columns.visitors" DESC,
"context.columns.breakdown_value" ASC
""",
                timings=self.timings,
                placeholders={
                    "breakdown_value": self._counts_breakdown_value(),
                    "where_breakdown": self.where_breakdown(),
                    "all_properties": self._all_properties(),
                    "date_from": self._date_from(),
                    "date_to": self._date_to(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _to_main_query_with_session_properties(self) -> ast.SelectQuery:
        with self.timings.measure("stats_table_query"):
            query = parse_select(
                """
SELECT
    breakdown_value AS "context.columns.breakdown_value",
    count(person_id) AS "context.columns.visitors",
    sum(filtered_pageview_count) AS "context.columns.views"
FROM (
    SELECT
        any(person_id) AS person_id,
        count() AS filtered_pageview_count,
        {breakdown_value} AS breakdown_value
    FROM events
    JOIN sessions
    ON events.`$session_id` = sessions.session_id
    WHERE and(
        timestamp >= {date_from},
        timestamp < {date_to},
        events.event == '$pageview',
        {event_properties},
        {session_properties},
        {where_breakdown}
    )
    GROUP BY events.`$session_id`, breakdown_value
)
GROUP BY "context.columns.breakdown_value"
ORDER BY "context.columns.visitors" DESC,
"context.columns.breakdown_value" ASC
""",
                timings=self.timings,
                placeholders={
                    "breakdown_value": self._counts_breakdown_value(),
                    "where_breakdown": self.where_breakdown(),
                    "event_properties": self._event_properties(),
                    "session_properties": self._session_properties(),
                    "date_from": self._date_from(),
                    "date_to": self._date_to(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def to_entry_bounce_query(self) -> ast.SelectQuery:
        with self.timings.measure("stats_table_query"):
            query = parse_select(
                """
SELECT
    breakdown_value AS "context.columns.breakdown_value",
    count(person_id) AS "context.columns.visitors",
    sum(filtered_pageview_count) AS "context.columns.views",
    avg(is_bounce) AS "context.columns.bounce_rate"
FROM (
    SELECT
        any(person_id) AS person_id,
        count() AS filtered_pageview_count,
        {bounce_breakdown} AS breakdown_value,
        any(sessions.$is_bounce) AS is_bounce
    FROM events
    JOIN sessions
    ON events.`$session_id` = sessions.session_id
    WHERE and(
        timestamp >= {date_from},
        timestamp < {date_to},
        events.event == '$pageview',
        {event_properties},
        {session_properties},
        {where_breakdown}
    )
    GROUP BY events.`$session_id`, breakdown_value
)
GROUP BY "context.columns.breakdown_value"
ORDER BY "context.columns.visitors" DESC,
"context.columns.breakdown_value" ASC
""",
                timings=self.timings,
                placeholders={
                    "bounce_breakdown": self._bounce_entry_pathname_breakdown(),
                    "where_breakdown": self.where_breakdown(),
                    "session_properties": self._session_properties(),
                    "event_properties": self._event_properties(),
                    "date_from": self._date_from(),
                    "date_to": self._date_to(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def to_path_scroll_bounce_query(self) -> ast.SelectQuery:
        if self.query.breakdownBy != WebStatsBreakdown.Page:
            raise NotImplementedError("Scroll depth is only supported for page breakdowns")

        with self.timings.measure("stats_table_bounce_query"):
            query = parse_select(
                """
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    counts.visitors AS "context.columns.visitors",
    counts.views AS "context.columns.views",
    bounce.bounce_rate AS "context.columns.bounce_rate",
    scroll.average_scroll_percentage AS "context.columns.average_scroll_percentage",
    scroll.scroll_gt80_percentage AS "context.columns.scroll_gt80_percentage"
FROM (
    SELECT
        breakdown_value,
        count(person_id) AS visitors,
        sum(filtered_pageview_count) AS views
    FROM (
        SELECT
            any(person_id) AS person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value
        FROM events
        JOIN sessions
        ON events.`$session_id` = sessions.session_id
        WHERE and(
            timestamp >= {date_from},
            timestamp < {date_to},
            events.event == '$pageview',
            {event_properties},
            {session_properties},
            breakdown_value IS NOT NULL
        )
        GROUP BY events.`$session_id`, breakdown_value
    )
    GROUP BY breakdown_value
) AS counts
LEFT JOIN (
    SELECT
        breakdown_value,
        avg(is_bounce) AS bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value, -- use $entry_pathname to find the bounce rate for sessions that started on this pathname
            any(session.`$is_bounce`) AS is_bounce
        FROM events
        JOIN sessions
        ON events.`$session_id` = sessions.session_id
        WHERE and(
            timestamp >= {date_from},
            timestamp < {date_to},
            events.event == '$pageview',
            {event_properties},
            {session_properties},
            breakdown_value IS NOT NULL
        )
        GROUP BY events.`$session_id`, breakdown_value
    )
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
LEFT JOIN (
    SELECT
        breakdown_value,
        avgMerge(average_scroll_percentage_state) AS average_scroll_percentage,
        avgMerge(scroll_gt80_percentage_state) AS scroll_gt80_percentage
    FROM (
        SELECT
            {scroll_breakdown_value} AS breakdown_value, -- use $prev_pageview_pathname to find the scroll depth when leaving this pathname
            avgState(CASE
                WHEN toFloat(events.properties.`$prev_pageview_max_content_percentage`) IS NULL THEN NULL
                WHEN toFloat(events.properties.`$prev_pageview_max_content_percentage`) > 0.8 THEN 1
                ELSE 0
                END
            ) AS scroll_gt80_percentage_state,
            avgState(toFloat(events.properties.`$prev_pageview_max_scroll_percentage`)) as average_scroll_percentage_state
        FROM events
        JOIN sessions
        ON events.`$session_id` = sessions.session_id
        WHERE and(
            timestamp >= {date_from},
            timestamp < {date_to},
            or(events.event == '$pageview', events.event == '$pageleave'),
            {event_properties_for_scroll},
            {session_properties},
            breakdown_value IS NOT NULL
        )
        GROUP BY events.`$session_id`, breakdown_value
    )
    GROUP BY breakdown_value
) AS scroll
ON counts.breakdown_value = scroll.breakdown_value
ORDER BY "context.columns.visitors" DESC,
"context.columns.breakdown_value" ASC
""",
                timings=self.timings,
                placeholders={
                    "session_properties": self._session_properties(),
                    "event_properties": self._event_properties(),
                    "event_properties_for_scroll": self._event_properties_for_scroll(),
                    "date_from": self._date_from(),
                    "date_to": self._date_to(),
                    "breakdown_value": self._counts_breakdown_value(),
                    "scroll_breakdown_value": self._scroll_prev_pathname_breakdown(),
                    "bounce_breakdown_value": self._bounce_entry_pathname_breakdown(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def to_path_bounce_query(self) -> ast.SelectQuery:
        if self.query.breakdownBy not in [WebStatsBreakdown.InitialPage, WebStatsBreakdown.Page]:
            raise NotImplementedError("Bounce rate is only supported for page breakdowns")

        with self.timings.measure("stats_table_scroll_query"):
            query = parse_select(
                """
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    counts.visitors AS "context.columns.visitors",
    counts.views AS "context.columns.views",
    bounce.bounce_rate AS "context.columns.bounce_rate"
FROM (
    SELECT
        breakdown_value,
        count(person_id) AS visitors,
        sum(filtered_pageview_count) AS views
    FROM (
        SELECT
            any(person_id) AS person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value
        FROM events
        JOIN sessions
        ON events.`$session_id` = sessions.session_id
        WHERE and(
            timestamp >= {date_from},
            timestamp < {date_to},
            events.event == '$pageview',
            {event_properties},
            {session_properties},
            {where_breakdown}
        )
        GROUP BY events.`$session_id`, breakdown_value
    )
    GROUP BY breakdown_value
) as counts
LEFT JOIN (
    SELECT
        breakdown_value,
        avg(is_bounce) AS bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value, -- use $entry_pathname to find the bounce rate for sessions that started on this pathname
            any(session.`$is_bounce`) AS is_bounce
        FROM events
        JOIN sessions
        ON events.`$session_id` = sessions.session_id
        WHERE and(
            timestamp >= {date_from},
            timestamp < {date_to},
            events.event == '$pageview',
            {event_properties},
            {session_properties},
            breakdown_value IS NOT NULL
        )
        GROUP BY events.`$session_id`, breakdown_value
    )
    GROUP BY breakdown_value
) as bounce
ON counts.breakdown_value = bounce.breakdown_value
ORDER BY "context.columns.visitors" DESC,
"context.columns.breakdown_value" ASC
""",
                timings=self.timings,
                placeholders={
                    "breakdown_value": self._counts_breakdown_value(),
                    "where_breakdown": self.where_breakdown(),
                    "session_properties": self._session_properties(),
                    "event_properties": self._event_properties(),
                    "date_from": self._date_from(),
                    "date_to": self._date_to(),
                    "bounce_breakdown_value": self._bounce_entry_pathname_breakdown(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _event_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _event_properties_for_scroll(self) -> ast.Expr:
        def map_scroll_property(property: Union[EventPropertyFilter, PersonPropertyFilter]):
            if get_property_type(property) == "event" and get_property_key(property) == "$pathname":
                return EventPropertyFilter(
                    key="$prev_pageview_pathname",
                    operator=get_property_operator(property),
                    value=get_property_value(property),
                )
            return property

        properties = [
            map_scroll_property(p)
            for p in self.query.properties + self._test_account_filters
            if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _has_session_properties(self) -> bool:
        return any(
            get_property_type(p) == "session" for p in self.query.properties + self._test_account_filters
        ) or self.query.breakdownBy in {
            WebStatsBreakdown.InitialChannelType,
            WebStatsBreakdown.InitialReferringDomain,
            WebStatsBreakdown.InitialUTMSource,
            WebStatsBreakdown.InitialUTMCampaign,
            WebStatsBreakdown.InitialUTMMedium,
            WebStatsBreakdown.InitialUTMTerm,
            WebStatsBreakdown.InitialUTMContent,
            WebStatsBreakdown.InitialPage,
            WebStatsBreakdown.ExitPage,
        }

    def _session_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.team, scope="session")

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    def _date_to(self) -> ast.Expr:
        return self.query_date_range.date_to_as_hogql()

    def _date_from(self) -> ast.Expr:
        return self.query_date_range.date_from_as_hogql()

    def calculate(self):
        response = self.paginator.execute_hogql_query(
            query_type="stats_table_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = self.paginator.results

        assert results is not None

        results_mapped = map_columns(
            results,
            {
                1: self._unsample,  # views
                2: self._unsample,  # visitors
            },
        )

        return WebStatsTableQueryResponse(
            columns=response.columns,
            results=results_mapped,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def _counts_breakdown_value(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.Page:
                return self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$pathname"]))
            case WebStatsBreakdown.InitialPage:
                return self._apply_path_cleaning(ast.Field(chain=["sessions", "$entry_pathname"]))
            case WebStatsBreakdown.ExitPage:
                return self._apply_path_cleaning(ast.Field(chain=["sessions", "$exit_pathname"]))
            case WebStatsBreakdown.InitialReferringDomain:
                return ast.Field(chain=["sessions", "$entry_referring_domain"])
            case WebStatsBreakdown.InitialUTMSource:
                return ast.Field(chain=["sessions", "$entry_utm_source"])
            case WebStatsBreakdown.InitialUTMCampaign:
                return ast.Field(chain=["sessions", "$entry_utm_campaign"])
            case WebStatsBreakdown.InitialUTMMedium:
                return ast.Field(chain=["sessions", "$entry_utm_medium"])
            case WebStatsBreakdown.InitialUTMTerm:
                return ast.Field(chain=["sessions", "$entry_utm_term"])
            case WebStatsBreakdown.InitialUTMContent:
                return ast.Field(chain=["sessions", "$entry_utm_content"])
            case WebStatsBreakdown.InitialChannelType:
                return ast.Field(chain=["sessions", "$channel_type"])
            case WebStatsBreakdown.Browser:
                return ast.Field(chain=["properties", "$browser"])
            case WebStatsBreakdown.OS:
                return ast.Field(chain=["properties", "$os"])
            case WebStatsBreakdown.DeviceType:
                return ast.Field(chain=["properties", "$device_type"])
            case WebStatsBreakdown.Country:
                return ast.Field(chain=["properties", "$geoip_country_code"])
            case WebStatsBreakdown.Region:
                return parse_expr(
                    "tuple(properties.$geoip_country_code, properties.$geoip_subdivision_1_code, properties.$geoip_subdivision_1_name)"
                )
            case WebStatsBreakdown.City:
                return parse_expr("tuple(properties.$geoip_country_code, properties.$geoip_city_name)")
            case _:
                raise NotImplementedError("Breakdown not implemented")

    def where_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.Region:
                return parse_expr("tupleElement(breakdown_value, 2) IS NOT NULL")
            case WebStatsBreakdown.City:
                return parse_expr("tupleElement(breakdown_value, 2) IS NOT NULL")
            case WebStatsBreakdown.InitialChannelType:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMSource:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMCampaign:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMMedium:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMTerm:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMContent:
                return parse_expr("TRUE")  # actually show null values
            case _:
                return parse_expr("breakdown_value IS NOT NULL")

    def _scroll_prev_pathname_breakdown(self):
        return self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$prev_pageview_pathname"]))

    def _bounce_entry_pathname_breakdown(self):
        return self._apply_path_cleaning(ast.Field(chain=["sessions", "$entry_pathname"]))

    def _apply_path_cleaning(self, path_expr: ast.Expr) -> ast.Expr:
        if not self.query.doPathCleaning or not self.team.path_cleaning_filters:
            return path_expr

        for replacement in self.team.path_cleaning_filter_models():
            path_expr = ast.Call(
                name="replaceRegexpAll",
                args=[
                    path_expr,
                    ast.Constant(value=replacement.regex),
                    ast.Constant(value=replacement.alias),
                ],
            )

        return path_expr
