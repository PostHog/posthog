from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.web_analytics.pre_aggregated.properties import WEB_OVERVIEW_SUPPORTED_PROPERTIES
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner


class WebOverviewPreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    def __init__(self, runner: "WebOverviewQueryRunner") -> None:
        super().__init__(runner, supported_props_filters=WEB_OVERVIEW_SUPPORTED_PROPERTIES)

    def get_query(self) -> ast.SelectQuery:
        previous_period_filter, current_period_filter = self.get_date_ranges()

        table_name = self.bounces_table

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
        FROM {table_name}
        """,
            placeholders={
                "table_name": ast.Field(chain=[table_name]),
                "unique_persons_current": self._uniq_merge_if("persons_uniq_state", current_period_filter),
                "unique_persons_previous": self._uniq_merge_if("persons_uniq_state", previous_period_filter),
                "pageviews_current": self._sum_merge_if("pageviews_count_state", current_period_filter),
                "pageviews_previous": self._sum_merge_if("pageviews_count_state", previous_period_filter),
                "unique_sessions_current": self._uniq_merge_if("sessions_uniq_state", current_period_filter),
                "unique_sessions_previous": self._uniq_merge_if("sessions_uniq_state", previous_period_filter),
                "avg_session_duration_current": self._safe_avg_sessions(
                    "total_session_duration_state", "total_session_count_state", current_period_filter
                ),
                "avg_session_duration_previous": self._safe_avg_sessions(
                    "total_session_duration_state", "total_session_count_state", previous_period_filter
                ),
                "bounce_rate_current": self._safe_avg_sessions(
                    "bounces_count_state", "sessions_uniq_state", current_period_filter
                ),
                "bounce_rate_previous": self._safe_avg_sessions(
                    "bounces_count_state", "sessions_uniq_state", previous_period_filter
                ),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        filters = self._get_filters(table_name=table_name)
        if filters:
            query.where = filters

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

    def _safe_avg_sessions(self, metric_state: str, denominator_state: str, period_filter: ast.Expr) -> ast.Call:
        metric_sum = self._sum_merge_if(metric_state, period_filter)

        if denominator_state == "sessions_uniq_state":
            denominator_count = self._uniq_merge_if(denominator_state, period_filter)
        else:
            denominator_count = self._sum_merge_if(denominator_state, period_filter)

        return ast.Call(
            name="if",
            args=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=denominator_count,
                    right=ast.Constant(value=0),
                ),
                ast.Call(
                    name="divide",
                    args=[metric_sum, denominator_count],
                ),
                ast.Constant(value=0),
            ],
        )
