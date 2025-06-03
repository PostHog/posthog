from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.pre_aggregated.properties import WEB_OVERVIEW_SUPPORTED_PROPERTIES

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner


class WebOverviewPreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    def __init__(self, runner: "WebOverviewQueryRunner") -> None:
        super().__init__(runner, supported_props_filters=WEB_OVERVIEW_SUPPORTED_PROPERTIES)

    def get_query(self) -> ast.SelectQuery:
        if self._includes_current_day():
            return self._get_union_query()
        else:
            return self._get_daily_only_query()

    def _get_daily_only_query(self) -> ast.SelectQuery:
        """Query for date ranges that don't include current day - use daily tables only."""
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
        FROM web_bounces_daily FINAL
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
                "bounce_rate_current": self._safe_avg_sessions("bounces_count_state", current_period_filter),
                "bounce_rate_previous": self._safe_avg_sessions("bounces_count_state", previous_period_filter),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        filters = self._get_filters(table_name="web_bounces_daily")
        if filters:
            query.where = filters

        return query

    def _get_union_query(self) -> ast.SelectQuery:
        """Query that combines daily and hourly data using UNION ALL."""
        # Get date ranges for each part of the union
        daily_previous_filter, daily_current_filter = self.get_date_ranges_for_union(granularity="daily")
        hourly_previous_filter, hourly_current_filter = self.get_date_ranges_for_union(granularity="hourly")

        # Daily part query
        daily_query = parse_select(
            """
            SELECT
                toDate(day_bucket) as bucket_date,
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
            FROM web_bounces_daily FINAL
            """,
            placeholders={
                "unique_persons_current": self._uniq_merge_if("persons_uniq_state", daily_current_filter),
                "unique_persons_previous": self._uniq_merge_if("persons_uniq_state", daily_previous_filter),
                "pageviews_current": self._sum_merge_if("pageviews_count_state", daily_current_filter),
                "pageviews_previous": self._sum_merge_if("pageviews_count_state", daily_previous_filter),
                "unique_sessions_current": self._uniq_merge_if("sessions_uniq_state", daily_current_filter),
                "unique_sessions_previous": self._uniq_merge_if("sessions_uniq_state", daily_previous_filter),
                "avg_session_duration_current": self._safe_avg_sessions(
                    "total_session_duration_state", daily_current_filter
                ),
                "avg_session_duration_previous": self._safe_avg_sessions(
                    "total_session_duration_state", daily_previous_filter
                ),
                "bounce_rate_current": self._safe_avg_sessions("bounces_count_state", daily_current_filter),
                "bounce_rate_previous": self._safe_avg_sessions("bounces_count_state", daily_previous_filter),
            },
        )

        # Hourly part query
        hourly_query = parse_select(
            """
            SELECT
                toDate(hour_bucket) as bucket_date,
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
            FROM web_bounces_hourly FINAL
            """,
            placeholders={
                "unique_persons_current": self._uniq_merge_if("persons_uniq_state", hourly_current_filter),
                "unique_persons_previous": self._uniq_merge_if("persons_uniq_state", hourly_previous_filter),
                "pageviews_current": self._sum_merge_if("pageviews_count_state", hourly_current_filter),
                "pageviews_previous": self._sum_merge_if("pageviews_count_state", hourly_previous_filter),
                "unique_sessions_current": self._uniq_merge_if("sessions_uniq_state", hourly_current_filter),
                "unique_sessions_previous": self._uniq_merge_if("sessions_uniq_state", hourly_previous_filter),
                "avg_session_duration_current": self._safe_avg_sessions(
                    "total_session_duration_state", hourly_current_filter
                ),
                "avg_session_duration_previous": self._safe_avg_sessions(
                    "total_session_duration_state", hourly_previous_filter
                ),
                "bounce_rate_current": self._safe_avg_sessions("bounces_count_state", hourly_current_filter),
                "bounce_rate_previous": self._safe_avg_sessions("bounces_count_state", hourly_previous_filter),
            },
        )

        # Add filters to both parts
        daily_filters = self._get_filters_for_daily_part("web_bounces_daily")
        hourly_filters = self._get_filters_for_hourly_part("web_bounces_hourly")

        assert isinstance(daily_query, ast.SelectQuery)
        assert isinstance(hourly_query, ast.SelectQuery)

        daily_query.where = daily_filters
        hourly_query.where = hourly_filters

        # Create the UNION ALL and wrap it in an aggregation query
        union_query = ast.SelectUnionQuery(select_queries=[daily_query, hourly_query])

        # Wrap the union in a final aggregation query
        final_query = parse_select(
            """
            SELECT
                sum(unique_persons) AS unique_persons,
                sum(previous_unique_persons) AS previous_unique_persons,
                sum(pageviews) AS pageviews,
                sum(previous_pageviews) AS previous_pageviews,
                sum(unique_sessions) AS unique_sessions,
                sum(previous_unique_sessions) AS previous_unique_sessions,
                if(sum(unique_sessions) > 0, sum(avg_session_duration * unique_sessions) / sum(unique_sessions), 0) AS avg_session_duration,
                if(sum(previous_unique_sessions) > 0, sum(previous_avg_session_duration * previous_unique_sessions) / sum(previous_unique_sessions), 0) AS previous_avg_session_duration,
                if(sum(unique_sessions) > 0, sum(bounce_rate * unique_sessions) / sum(unique_sessions), 0) AS bounce_rate,
                if(sum(previous_unique_sessions) > 0, sum(previous_bounce_rate * previous_unique_sessions) / sum(previous_unique_sessions), 0) AS previous_bounce_rate,
                NULL AS revenue,
                NULL AS previous_revenue
            FROM ({union_subquery})
            """,
            placeholders={
                "union_subquery": union_query,
            },
        )

        assert isinstance(final_query, ast.SelectQuery)
        return final_query

    def _uniq_merge_if(self, state_field: str, period_filter: ast.Expr) -> ast.Call:
        return ast.Call(
            name="uniqMergeIf",
            args=[
                ast.Field(chain=[state_field]),
                period_filter,
            ],
        )

    def _sum_merge_if(self, state_field: str, period_filter: ast.Expr) -> ast.Call:
        return ast.Call(
            name="sumMergeIf",
            args=[
                ast.Field(chain=[state_field]),
                period_filter,
            ],
        )

    def _safe_avg_sessions(self, metric_state: str, period_filter: ast.Expr) -> ast.Call:
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
