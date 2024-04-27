from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
    map_columns,
)
from posthog.hogql_queries.web_analytics.web_overview import get_property_type
from posthog.schema import (
    WebStatsTableQuery,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
)


class WebStatsTableQueryRunner(WebAnalyticsQueryRunner):
    query: WebStatsTableQuery
    query_type = WebStatsTableQuery
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("date_expr"):
            date_from = self.query_date_range.date_from_as_hogql()
            date_to = self.query_date_range.date_to_as_hogql()

        with self.timings.measure("stats_table_query"):
            query = parse_select(
                """
SELECT
    "context.columns.breakdown_value",
    count(person_id) AS "context.columns.visitors",
    sum(filtered_pageview_count) AS "context.columns.views"
FROM (
    SELECT
        any(person_id) AS person_id,
        count() AS filtered_pageview_count,
        {breakdown_value} AS "context.columns.breakdown_value"
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
    GROUP BY events.`$session_id`, "context.columns.breakdown_value"
)
GROUP BY "context.columns.breakdown_value"
ORDER BY "context.columns.visitors" DESC,
"context.columns.breakdown_value" DESC
""",
                timings=self.timings,
                placeholders={
                    "breakdown_value": self._counts_breakdown_value(),
                    "where_breakdown": self.where_breakdown(),
                    "session_properties": self._session_properties(),
                    "event_properties": self._event_properties(),
                    "date_from": date_from,
                    "date_to": date_to,
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _event_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _session_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.team, scope="session")

    def calculate(self):
        response = self.paginator.execute_hogql_query(
            query_type="top_sources_query",
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
                return ast.Field(chain=["sessions", "$initial_referring_domain"])
            case WebStatsBreakdown.InitialUTMSource:
                return ast.Field(chain=["sessions", "$initial_utm_source"])
            case WebStatsBreakdown.InitialUTMCampaign:
                return ast.Field(chain=["sessions", "$initial_utm_campaign"])
            case WebStatsBreakdown.InitialUTMMedium:
                return ast.Field(chain=["sessions", "$initial_utm_medium"])
            case WebStatsBreakdown.InitialUTMTerm:
                return ast.Field(chain=["sessions", "$initial_utm_term"])
            case WebStatsBreakdown.InitialUTMContent:
                return ast.Field(chain=["sessions", "$initial_utm_content"])
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
                return parse_expr('tupleElement("context.columns.breakdown_value", 2) IS NOT NULL')
            case WebStatsBreakdown.City:
                return parse_expr('tupleElement("context.columns.breakdown_value", 2) IS NOT NULL')
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
                return parse_expr('"context.columns.breakdown_value" IS NOT NULL')

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
