from typing import TYPE_CHECKING, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

SUPPORTED_PROPERTIES = {
    "$host": "host",
    "$device_type": "device_type",
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

            {safe_avg_sessions("total_bounces", current_period_filter)} AS bounce_rate,
            {safe_avg_sessions("total_bounces", previous_period_filter)} AS previous_bounce_rate,

            NULL AS revenue,
            NULL AS previous_revenue
        FROM web_overview_daily
        """

        query = cast(ast.SelectQuery, parse_select(query_str))

        filters = self._get_filters(table_name="web_overview_daily")
        if filters:
            query.where = filters

        return query
