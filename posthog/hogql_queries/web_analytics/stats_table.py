from posthog.hogql import ast
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.ctes import (
    COUNTS_CTE,
    BOUNCE_RATE_CTE,
)
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.schema import (
    WebStatsTableQuery,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
)


class WebStatsTableQueryRunner(WebAnalyticsQueryRunner):
    query: WebStatsTableQuery
    query_type = WebStatsTableQuery

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("bounce_rate_query"):
            bounce_rate_query = parse_select(
                BOUNCE_RATE_CTE,
                timings=self.timings,
                placeholders={
                    "session_where": self.session_where(),
                    "session_having": self.session_having(),
                    "breakdown_by": self.bounce_breakdown(),
                },
                backend="cpp",
            )
        with self.timings.measure("counts_query"):
            counts_query = parse_select(
                COUNTS_CTE,
                timings=self.timings,
                placeholders={
                    "counts_where": self.events_where(),
                    "breakdown_by": self.counts_breakdown(),
                },
                backend="cpp",
            )
        with self.timings.measure("top_pages_query"):
            top_sources_query = parse_select(
                """
SELECT
    counts.breakdown_value as "context.columns.breakdown_value",
    counts.total_pageviews as "context.columns.views",
    counts.unique_visitors as "context.columns.visitors",
    bounce_rate.bounce_rate as "context.columns.bounce_rate"
FROM
    {counts_query} AS counts
LEFT OUTER JOIN
    {bounce_rate_query} AS bounce_rate
ON
    counts.breakdown_value = bounce_rate.breakdown_value
WHERE
    {where_breakdown}
ORDER BY
    "context.columns.views" DESC
LIMIT 10
                """,
                timings=self.timings,
                placeholders={
                    "counts_query": counts_query,
                    "bounce_rate_query": bounce_rate_query,
                    "where_breakdown": self.where_breakdown(),
                },
                backend="cpp",
            )
        return top_sources_query

    def calculate(self):
        response = execute_hogql_query(
            query_type="top_sources_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
        )

        return WebStatsTableQueryResponse(
            columns=response.columns,
            results=response.results,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
        )

    def counts_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.Page:
                return parse_expr("properties.$pathname")
            case WebStatsBreakdown.InitialPage:
                return parse_expr("properties.$set_once.$initial_pathname")
            case WebStatsBreakdown.InitialReferringDomain:
                return parse_expr("properties.$set_once.$initial_referring_domain")
            case WebStatsBreakdown.InitialUTMSource:
                return parse_expr("properties.$set_once.$initial_utm_source")
            case WebStatsBreakdown.InitialUTMCampaign:
                return parse_expr("properties.$set_once.$initial_utm_campaign")
            case WebStatsBreakdown.Browser:
                return parse_expr("properties.$browser")
            case WebStatsBreakdown.OS:
                return parse_expr("properties.$os")
            case WebStatsBreakdown.DeviceType:
                return parse_expr("properties.$device_type")
            case WebStatsBreakdown.Country:
                return parse_expr("properties.$geoip_country_code")
            case WebStatsBreakdown.Region:
                return parse_expr(
                    "tuple(properties.$geoip_country_code, properties.$geoip_subdivision_1_code, properties.$geoip_subdivision_1_name)"
                )
            case WebStatsBreakdown.City:
                return parse_expr("tuple(properties.$geoip_country_code, properties.$geoip_city_name)")
            case _:
                raise NotImplementedError("Breakdown not implemented")

    def bounce_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.Page:
                return parse_expr("any(properties.$set_once.$initial_pathname)")
            case WebStatsBreakdown.InitialPage:
                return parse_expr("any(properties.$set_once.$initial_pathname)")
            case WebStatsBreakdown.InitialReferringDomain:
                return parse_expr("any(properties.$set_once.$initial_referring_domain)")
            case WebStatsBreakdown.InitialUTMSource:
                return parse_expr("any(properties.$set_once.$initial_utm_source)")
            case WebStatsBreakdown.InitialUTMCampaign:
                return parse_expr("any(properties.$set_once.$initial_utm_campaign)")
            case WebStatsBreakdown.Browser:
                return parse_expr("any(properties.$browser)")
            case WebStatsBreakdown.OS:
                return parse_expr("any(properties.$os)")
            case WebStatsBreakdown.DeviceType:
                return parse_expr("any(properties.$device_type)")
            case WebStatsBreakdown.Country:
                return parse_expr("any(properties.$geoip_country_code)")
            case WebStatsBreakdown.Region:
                return parse_expr(
                    "any(tuple(properties.$geoip_country_code, properties.$geoip_subdivision_1_code, properties.$geoip_subdivision_1_name))"
                )
            case WebStatsBreakdown.City:
                return parse_expr("any(tuple(properties.$geoip_country_code, properties.$geoip_city_name))")
            case _:
                raise NotImplementedError("Breakdown not implemented")

    def where_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.Region:
                return parse_expr('tupleElement("context.columns.breakdown_value", 2) IS NOT NULL')
            case WebStatsBreakdown.City:
                return parse_expr('tupleElement("context.columns.breakdown_value", 2) IS NOT NULL')
            case WebStatsBreakdown.InitialUTMSource:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMCampaign:
                return parse_expr("TRUE")  # actually show null values
            case _:
                return parse_expr('"context.columns.breakdown_value" IS NOT NULL')
