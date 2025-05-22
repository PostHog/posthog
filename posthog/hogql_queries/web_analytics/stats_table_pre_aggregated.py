from typing import TYPE_CHECKING, Literal, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder
from posthog.schema import WebAnalyticsOrderByDirection, WebAnalyticsOrderByFields, WebStatsBreakdown

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner

# We can enable more filters here, but keeping the same as web_overview while we test in
STATS_TABLE_SUPPORTED_FILTERS = {
    "$host": "host",
    "$device_type": "device_type",
    # "$browser": "browser",
    # "$os": "os",
    # "$viewport": "viewport",
    # "$referring_domain": "referring_domain",
    # "$utm_source": "utm_source",
    # "$utm_medium": "utm_medium",
    # "$utm_campaign": "utm_campaign",
    # "$utm_term": "utm_term",
    # "$utm_content": "utm_content",
    # "$country": "country",
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
    ]

    def __init__(self, runner: "WebStatsTableQueryRunner") -> None:
        _table_name = "web_stats_daily"

        if runner.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            _table_name = "web_bounces_daily"

        super().__init__(runner=runner, supported_props_filters=STATS_TABLE_SUPPORTED_FILTERS, table_name=_table_name)

    def can_use_preaggregated_tables(self) -> bool:
        if not super().can_use_preaggregated_tables():
            return False

        return self.runner.query.breakdownBy in self.SUPPORTED_BREAKDOWNS

    def _bounce_rate_query(self) -> str:
        # Like in the original stats_table, we will need this method to build the "Paths" tile so it is a special breakdown
        previous_period_filter, current_period_filter = self.get_date_ranges()

        query_str = f"""
        SELECT
            entry_path as `context.columns.breakdown_value`,
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
        FROM {self.table_name}
        GROUP BY `context.columns.breakdown_value`
        """

        return query_str

    def get_query(self) -> ast.SelectQuery:
        previous_period_filter, current_period_filter = self.get_date_ranges()

        query_str = ""
        if self.runner.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            query_str = self._bounce_rate_query()
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
            FROM {self.table_name}
            GROUP BY `context.columns.breakdown_value`
            """

        query = cast(ast.SelectQuery, parse_select(query_str))

        filters = self._get_filters()
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
            elif field == WebAnalyticsOrderByFields.BOUNCE_RATE:
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
                return "country"
            case WebStatsBreakdown.INITIAL_PAGE:
                return "entry_path"
