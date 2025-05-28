from typing import TYPE_CHECKING, Literal, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder
from posthog.schema import WebAnalyticsOrderByDirection, WebAnalyticsOrderByFields, WebStatsBreakdown

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner

# Keep those in sync with frontend/src/scenes/web-analytics/WebPropertyFilters.tsx
STATS_TABLE_SUPPORTED_FILTERS = {
    "$entry_pathname": "entry_pathname",
    "$pathname": "pathname",
    "$end_pathname": "end_pathname",
    "$host": "host",
    "$device_type": "device_type",
    "$browser": "browser",
    "$os": "os",
    "$referring_domain": "referring_domain",
    "$entry_utm_source": "utm_source",
    "$entry_utm_medium": "utm_medium",
    "$entry_utm_campaign": "utm_campaign",
    "$entry_utm_term": "utm_term",
    "$entry_utm_content": "utm_content",
    "$geoip_country_name": "country_name",
    "$geoip_country_code": "country_code",
    "$geoip_city_name": "city_name",
    "$geoip_subdivision_1_code": "region_code",
}


class StatsTablePreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    SUPPORTED_BREAKDOWNS = [
        WebStatsBreakdown.DEVICE_TYPE,
        WebStatsBreakdown.BROWSER,
        WebStatsBreakdown.OS,
        WebStatsBreakdown.VIEWPORT,
        WebStatsBreakdown.INITIAL_REFERRING_DOMAIN,
        WebStatsBreakdown.INITIAL_UTM_SOURCE,
        WebStatsBreakdown.INITIAL_UTM_MEDIUM,
        WebStatsBreakdown.INITIAL_UTM_CAMPAIGN,
        WebStatsBreakdown.INITIAL_UTM_TERM,
        WebStatsBreakdown.INITIAL_UTM_CONTENT,
        WebStatsBreakdown.COUNTRY,
        WebStatsBreakdown.INITIAL_PAGE,
        WebStatsBreakdown.PAGE,
        WebStatsBreakdown.EXIT_PAGE,
    ]

    def __init__(self, runner: "WebStatsTableQueryRunner") -> None:
        super().__init__(runner=runner, supported_props_filters=STATS_TABLE_SUPPORTED_FILTERS)

    def can_use_preaggregated_tables(self) -> bool:
        if not super().can_use_preaggregated_tables():
            return False

        return self.runner.query.breakdownBy in self.SUPPORTED_BREAKDOWNS

    def _bounce_rate_query(self, include_filters: bool = False) -> str:
        # Like in the original stats_table, we will need this method to build the "Paths" tile so it is a special breakdown
        previous_period_filter, current_period_filter = self.get_date_ranges()

        query_str = f"""
        SELECT
            entry_pathname as `context.columns.breakdown_value`,
            tuple(
                uniqMergeIf(persons_uniq_state, {current_period_filter}),
                uniqMergeIf(persons_uniq_state, {previous_period_filter})
            ) AS `context.columns.visitors`,
            tuple(
                sumMergeIf(pageviews_count_state, {current_period_filter}),
                sumMergeIf(pageviews_count_state, {previous_period_filter})
            ) as `context.columns.views`,
            tuple(
                (sumMergeIf(bounces_count_state, {current_period_filter}) / nullif(uniqMergeIf(sessions_uniq_state, {current_period_filter}), 0)),
                (sumMergeIf(bounces_count_state, {previous_period_filter}) / nullif(uniqMergeIf(sessions_uniq_state, {previous_period_filter}), 0))
            ) as `context.columns.bounce_rate`
        FROM web_bounces_daily
        GROUP BY `context.columns.breakdown_value`
        """

        return query_str

    def _path_query(self) -> str:
        previous_period_filter, current_period_filter = self.get_date_ranges(table_name="p")

        query_str = f"""
        SELECT
            pathname as `context.columns.breakdown_value`,
            tuple(
                uniqMergeIf(p.persons_uniq_state, {current_period_filter}),
                uniqMergeIf(p.persons_uniq_state, {previous_period_filter})
            ) AS `context.columns.visitors`,
            tuple(
                sumMergeIf(p.pageviews_count_state, {current_period_filter}),
                sumMergeIf(p.pageviews_count_state, {previous_period_filter})
            ) as `context.columns.views`,
            any(bounces.`context.columns.bounce_rate`) as `context.columns.bounce_rate`
        FROM
            web_stats_daily p
        LEFT JOIN ({self._bounce_rate_query()}) bounces
            ON p.pathname = bounces.`context.columns.breakdown_value`
        GROUP BY `context.columns.breakdown_value`
        """

        return query_str

    def get_query(self) -> ast.SelectQuery:
        previous_period_filter, current_period_filter = self.get_date_ranges()

        query_str = ""
        table_name = "web_stats_daily"
        if self.runner.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            query_str = self._bounce_rate_query()
            table_name = "web_bounces_daily"
        elif self.runner.query.breakdownBy == WebStatsBreakdown.PAGE:
            query_str = self._path_query()
            table_name = "p"
        else:
            breakdown_field = self._get_breakdown_field()
            query_str = f"""
            SELECT
                {breakdown_field} as `context.columns.breakdown_value`,
                tuple(
                    uniqMergeIf(persons_uniq_state, {current_period_filter}),
                    uniqMergeIf(persons_uniq_state, {previous_period_filter})
                ) AS `context.columns.visitors`,
                tuple(
                    sumMergeIf(pageviews_count_state, {current_period_filter}),
                    sumMergeIf(pageviews_count_state, {previous_period_filter})
                ) as `context.columns.views`
            FROM web_stats_daily
            GROUP BY `context.columns.breakdown_value`
            """

        query = cast(ast.SelectQuery, parse_select(query_str))

        filters = self._get_filters(table_name=table_name)
        if filters:
            query.where = filters

        query.order_by = [self._get_order_by()]

        return query

    def _get_order_by(self):
        if self.runner.query.orderBy:
            column = None
            direction: Literal["ASC", "DESC"] = "DESC"
            field = cast(WebAnalyticsOrderByFields, self.runner.query.orderBy[0])
            direction = cast(WebAnalyticsOrderByDirection, self.runner.query.orderBy[1]).value

            if field == WebAnalyticsOrderByFields.VISITORS:
                column = "context.columns.visitors"
            elif field == WebAnalyticsOrderByFields.VIEWS:
                column = "context.columns.views"
            elif field == WebAnalyticsOrderByFields.BOUNCE_RATE and self.runner.query.breakdownBy in [
                WebStatsBreakdown.INITIAL_PAGE,
                WebStatsBreakdown.PAGE,
            ]:
                column = "context.columns.bounce_rate"

            if column:
                return ast.OrderExpr(expr=ast.Field(chain=[column]), order=direction)

        return ast.OrderExpr(expr=ast.Field(chain=["context.columns.views"]), order="DESC")

    def _get_breakdown_field(self):
        match self.runner.query.breakdownBy:
            case WebStatsBreakdown.DEVICE_TYPE:
                return "device_type"
            case WebStatsBreakdown.BROWSER:
                return "browser"
            case WebStatsBreakdown.OS:
                return "os"
            case WebStatsBreakdown.VIEWPORT:
                return "viewport"
            case WebStatsBreakdown.INITIAL_REFERRING_DOMAIN:
                return "referring_domain"
            case WebStatsBreakdown.INITIAL_UTM_SOURCE:
                return "utm_source"
            case WebStatsBreakdown.INITIAL_UTM_MEDIUM:
                return "utm_medium"
            case WebStatsBreakdown.INITIAL_UTM_CAMPAIGN:
                return "utm_campaign"
            case WebStatsBreakdown.INITIAL_UTM_TERM:
                return "utm_term"
            case WebStatsBreakdown.INITIAL_UTM_CONTENT:
                return "utm_content"
            case WebStatsBreakdown.COUNTRY:
                return "country_name"
            case WebStatsBreakdown.CITY:
                return "city_name"
            case WebStatsBreakdown.REGION:
                return "region_code"
            case WebStatsBreakdown.EXIT_PAGE:
                return "end_pathname"
