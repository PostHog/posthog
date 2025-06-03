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
        query = self._create_overview_query("web_bounces_daily")
        filters = self._get_filters(table_name="web_bounces_daily")
        if filters:
            query.where = filters
        return query

    def _get_union_query(self) -> ast.SelectQuery:
        """Query that combines daily and hourly data using UNION ALL."""
        # Create daily part - exclude current day
        daily_query = self._create_overview_query("web_bounces_daily", for_union=True)
        daily_period_filter = self._get_daily_period_filter("web_bounces_daily", exclude_current_day=True)
        daily_query.where = self._get_filters("web_bounces_daily", daily_period_filter)

        # Create hourly part - only current day
        hourly_query = self._create_overview_query("web_bounces_hourly", for_union=True)
        hourly_period_filter = self._get_hourly_period_filter("web_bounces_hourly", current_day_only=True)
        hourly_query.where = self._get_filters("web_bounces_hourly", hourly_period_filter)

        # Create UNION ALL and wrap in final aggregation
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

    def _create_overview_query(self, table_name: str, for_union: bool = False) -> ast.SelectQuery:
        """Create overview query for a single table."""
        if for_union:
            # For union parts, get date ranges specific to daily/hourly granularity
            granularity = "hourly" if "hourly" in table_name else "daily"
            previous_period_filter, current_period_filter = self.get_date_ranges_for_union(granularity)
            # Include bucket_date for union aggregation
            select_template = """
                SELECT
                    toDate(period_bucket) as bucket_date,
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
                FROM {table_name} FINAL
                """
        else:
            # For single table queries, use standard date ranges
            previous_period_filter, current_period_filter = self.get_date_ranges()
            select_template = """
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
                FROM {table_name} FINAL
                """

        query = parse_select(
            select_template,
            placeholders={
                "table_name": ast.Field(chain=[table_name]),
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
        return query

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
