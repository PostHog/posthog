from typing import TYPE_CHECKING, cast

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

        def safe_avg_sessions(metric, period_filter):
            sessions = f"uniqMergeIf(sessions_uniq_state, {period_filter})"
            return f"""
            if(
                {sessions} > 0,
                sumMergeIf({metric}_state, {period_filter}) / {sessions},
                0
            )"""

        query_str = f"""
        SELECT
            uniqMergeIf(persons_uniq_state, {current_period_filter}) AS unique_persons,
            uniqMergeIf(persons_uniq_state, {previous_period_filter}) AS previous_unique_persons,

            sumMergeIf(pageviews_count_state, {current_period_filter}) AS pageviews,
            sumMergeIf(pageviews_count_state, {previous_period_filter}) AS previous_pageviews,

            uniqMergeIf(sessions_uniq_state, {current_period_filter}) AS unique_sessions,
            uniqMergeIf(sessions_uniq_state, {previous_period_filter}) AS previous_unique_sessions,

            {safe_avg_sessions("total_session_duration", current_period_filter)} AS avg_session_duration,
            {safe_avg_sessions("total_session_duration", previous_period_filter)} AS previous_avg_session_duration,

            {safe_avg_sessions("bounces_count", current_period_filter)} AS bounce_rate,
            {safe_avg_sessions("bounces_count", previous_period_filter)} AS previous_bounce_rate,

            NULL AS revenue,
            NULL AS previous_revenue
        FROM web_bounces_daily
        """

        query = cast(ast.SelectQuery, parse_select(query_str))

        filters = self._get_filters(table_name="web_bounces_daily")
        if filters:
            query.where = filters

        return query
