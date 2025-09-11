from typing import Any

from posthog.schema import IntervalType, WebTrendsMetric

from posthog.hogql import ast

from posthog.hogql_queries.web_analytics.pre_aggregated.properties import WEB_ANALYTICS_TRENDS_SUPPORTED_FILTERS
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder

WEB_ANALYTICS_TRENDS_PRE_AGGREGATED_SUPPORTED_METRICS = [
    WebTrendsMetric.UNIQUE_USERS,
    WebTrendsMetric.PAGE_VIEWS,
    WebTrendsMetric.SESSIONS,
    WebTrendsMetric.BOUNCES,
    WebTrendsMetric.SESSION_DURATION,
    WebTrendsMetric.TOTAL_SESSIONS,
]


class TrendsPreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    def __init__(
        self, runner: Any
    ) -> None:  # TODO: Replace Any with WebAnalyticsTrendsQueryRunner when it is implemented
        super().__init__(runner=runner, supported_props_filters=WEB_ANALYTICS_TRENDS_SUPPORTED_FILTERS)

    def can_use_preaggregated_tables(self) -> bool:
        if not super().can_use_preaggregated_tables():
            return False

        # Pre-aggregated tables do not support granularity < a day, since they aggregate data by day
        if self.runner.query.interval not in [IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH]:
            return False

        if self.runner.query.metrics and not all(
            metric in WEB_ANALYTICS_TRENDS_PRE_AGGREGATED_SUPPORTED_METRICS for metric in self.runner.query.metrics
        ):
            return False

        # Pre-aggregated tables store data in UTC buckets, so we can only use them when not converting timezone
        if self.runner.modifiers and self.runner.modifiers.convertToProjectTimezone:
            return False

        return True

    def get_query(self) -> ast.SelectQuery:
        bucket_expr = self._get_bucket_expr()

        select_exprs: list[ast.Expr] = [bucket_expr]

        select_exprs.extend(self._get_metrics_exprs())

        query = ast.SelectQuery(
            select=select_exprs,
            select_from=ast.JoinExpr(table=ast.Field(chain=[self._get_table_name()])),
            where=self._get_filters(table_name=self._get_table_name()),
            group_by=[ast.Field(chain=["bucket"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["bucket"]), order="ASC")],
        )

        return query

    def _get_table_name(self) -> str:
        return "web_bounces_combined"

    def _get_interval_function(self) -> str:
        interval_function_map = {
            IntervalType.DAY: "toStartOfDay",
            IntervalType.WEEK: "toStartOfWeek",
            IntervalType.MONTH: "toStartOfMonth",
        }

        interval_function = interval_function_map[self.runner.query.interval]

        if not interval_function:
            raise ValueError(f"Unsupported interval: {self.runner.query.interval}")

        return interval_function

    def _get_bucket_expr(self) -> ast.Alias:
        interval_function = self._get_interval_function()

        bucket_expr = ast.Call(
            name=interval_function,
            args=[ast.Field(chain=["period_bucket"])],
        )

        return ast.Alias(
            alias="bucket",
            expr=bucket_expr,
        )

    def _get_metric_expr(self, metric: WebTrendsMetric) -> ast.Alias:
        if metric == WebTrendsMetric.UNIQUE_USERS:
            return ast.Alias(
                alias="unique_users",
                expr=ast.Call(
                    name="uniqMerge",
                    args=[ast.Field(chain=["persons_uniq_state"])],
                ),
            )
        elif metric == WebTrendsMetric.PAGE_VIEWS:
            return ast.Alias(
                alias="page_views",
                expr=ast.Call(
                    name="sumMerge",
                    args=[ast.Field(chain=["pageviews_count_state"])],
                ),
            )
        elif metric == WebTrendsMetric.SESSIONS:
            return ast.Alias(
                alias="sessions",
                expr=ast.Call(
                    name="uniqMerge",
                    args=[ast.Field(chain=["sessions_uniq_state"])],
                ),
            )
        elif metric == WebTrendsMetric.BOUNCES:
            return ast.Alias(
                alias="bounces",
                expr=ast.Call(
                    name="sumMerge",
                    args=[ast.Field(chain=["bounces_count_state"])],
                ),
            )
        elif metric == WebTrendsMetric.SESSION_DURATION:
            return ast.Alias(
                alias="session_duration",
                expr=ast.Call(
                    name="sumMerge",
                    args=[ast.Field(chain=["total_session_duration_state"])],
                ),
            )
        elif metric == WebTrendsMetric.TOTAL_SESSIONS:
            return ast.Alias(
                alias="total_sessions",
                expr=ast.Call(
                    name="sumMerge",
                    args=[ast.Field(chain=["total_session_count_state"])],
                ),
            )

        raise ValueError(f"Unknown metric: {metric}")

    def _get_metrics_exprs(self) -> list[ast.Alias]:
        metrics = self.runner.query.metrics or [WebTrendsMetric.UNIQUE_USERS]
        return [self._get_metric_expr(metric) for metric in metrics]
