from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

SUPPORTED_PROPERTIES = {
    "$host": "host",
    "$device_type": "device_type",
    # We convert the pathname to entry_pathname when filtering by pathname for the overview only.
    # This is the same workaround as the one used in the stats_table.py (see _event_properties_for_bounce_rate)
    # The actual way to keep 100% accuracy with the existing version is to join with web_stats_daily
    # and filter by pathname there. This is a compromise to keep the query simpler in the meantime as we
    # don't have access to all events to filter the inner query here.
    "$pathname": "entry_pathname",
    "$entry_pathname": "entry_pathname",
    "$end_pathname": "end_pathname",
    "$browser": "browser",
    "$os": "os",
    "$referring_domain": "referring_domain",
    "$entry_utm_source": "utm_source",
    "$entry_utm_medium": "utm_medium",
    "$entry_utm_campaign": "utm_campaign",
    "$entry_utm_term": "utm_term",
    "$entry_utm_content": "utm_content",
    "$geoip_country_code": "country_code",
    "$geoip_city_name": "city_name",
    "$geoip_subdivision_1_code": "region_code",
}


class WebOverviewPreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    def __init__(self, runner: "WebOverviewQueryRunner") -> None:
        super().__init__(runner, supported_props_filters=SUPPORTED_PROPERTIES)

    def get_query(self) -> ast.SelectQuery:
        previous_period_filter, current_period_filter = self.get_date_ranges()

        query = parse_select(
            """
            SELECT
                {unique_persons_current} AS unique_persons,
                {unique_persons_previous} AS previous_unique_persons,

                {pageviews_current} AS pageviews,
                {pageviews_previous} AS previous_pageviews,

                {unique_sessions_current} AS unique_sessions,
                {unique_sessions_previous} AS previous_unique_sessions,

                {avg_session_duration_current} AS avg_session_duration,
                {avg_session_duration_previous} AS previous_avg_session_duration,

                {bounce_rate_current} AS bounce_rate,
                {bounce_rate_previous} AS previous_bounce_rate,

                NULL AS revenue,
                NULL AS previous_revenue
        FROM web_bounces_daily
        """,
            placeholders={
                "unique_persons_current": self._uniq_merge_if("persons_uniq_state", current_period_filter),
                "unique_persons_previous": self._uniq_merge_if("persons_uniq_state", previous_period_filter),
                "pageviews_current": self._sum_merge_if("pageviews_count_state", current_period_filter),
                "pageviews_previous": self._sum_merge_if("pageviews_count_state", previous_period_filter),
                "unique_sessions_current": self._uniq_merge_if("sessions_uniq_state", current_period_filter),
                "unique_sessions_previous": self._uniq_merge_if("sessions_uniq_state", previous_period_filter),
                "avg_session_duration_current": self._safe_avg_sessions(
                    "total_session_duration_state", current_period_filter
                ),
                "avg_session_duration_previous": self._safe_avg_sessions(
                    "total_session_duration_state", previous_period_filter
                ),
                "bounce_rate_current": self._safe_avg_sessions("total_bounces_state", current_period_filter),
                "bounce_rate_previous": self._safe_avg_sessions("total_bounces_state", previous_period_filter),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        filters = self._get_filters(table_name="web_bounces_daily")
        if filters:
            query.where = filters

        return query

    def _uniq_merge_if(self, state_field: str, period_filter: ast.Expr) -> ast.Call:
        """Utility method to create uniqMergeIf expressions"""
        return ast.Call(
            name="uniqMergeIf",
            args=[
                ast.Field(chain=[state_field]),
                period_filter,
            ],
        )

    def _sum_merge_if(self, state_field: str, period_filter: ast.Expr) -> ast.Call:
        """Utility method to create sumMergeIf expressions"""
        return ast.Call(
            name="sumMergeIf",
            args=[
                ast.Field(chain=[state_field]),
                period_filter,
            ],
        )

    def _safe_avg_sessions(self, metric_state: str, period_filter: ast.Expr) -> ast.Call:
        """
        Utility method to safely calculate averages per session, avoiding division by zero.
        Returns: if(sessions > 0, metric / sessions, 0)
        """
        sessions_count = self._uniq_merge_if("sessions_uniq_state", period_filter)
        metric_sum = self._sum_merge_if(metric_state, period_filter)

        return ast.Call(
            name="if",
            args=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=sessions_count,
                    right=ast.Constant(value=0),
                ),
                ast.Call(
                    name="divide",
                    args=[metric_sum, sessions_count],
                ),
                ast.Constant(value=0),
            ],
        )
