from typing import TYPE_CHECKING, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.web_analytics.pre_aggregated.properties import WEB_OVERVIEW_SUPPORTED_PROPERTIES
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner


class WebOverviewPreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    def __init__(self, runner: "WebOverviewQueryRunner") -> None:
        super().__init__(runner, supported_props_filters=WEB_OVERVIEW_SUPPORTED_PROPERTIES)

    def get_query(self) -> ast.SelectQuery:
        previous_period_filter, current_period_filter = self.get_date_ranges()

        if self.runner.query.conversionGoal:
            return self._get_conversion_query(current_period_filter, previous_period_filter)

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

    def _get_conversion_query(
        self, current_period_filter: ast.Expr, previous_period_filter: ast.Expr
    ) -> ast.SelectQuery:
        """Build query for conversion goals using hybrid approach: pre-agg for visitors, raw events for conversions"""
        # Build subquery for conversions from raw events
        conversion_subquery = self._build_overview_conversion_subquery()

        # Build stats subquery from pre-aggregated table for visitor counts
        stats_subquery = parse_select(
            """
            SELECT
                {unique_persons_current} AS unique_persons,
                {unique_persons_previous} AS previous_unique_persons
            FROM {table_name}
            """,
            placeholders={
                "table_name": ast.Field(chain=[self.bounces_table]),
                "unique_persons_current": self._uniq_merge_if("persons_uniq_state", current_period_filter),
                "unique_persons_previous": self._uniq_merge_if("persons_uniq_state", previous_period_filter),
            },
        )

        assert isinstance(stats_subquery, ast.SelectQuery)
        filters = self._get_filters(table_name=self.bounces_table)
        if filters:
            stats_subquery.where = filters

        # Combine both queries
        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                stats.unique_persons,
                stats.previous_unique_persons,
                conversions.total_conversions,
                conversions.previous_total_conversions,
                conversions.unique_conversions,
                conversions.previous_unique_conversions,
                if(stats.unique_persons = 0, NULL, conversions.unique_conversions / stats.unique_persons) as conversion_rate,
                if(stats.previous_unique_persons = 0, NULL, conversions.previous_unique_conversions / stats.previous_unique_persons) as previous_conversion_rate,
                NULL as revenue,
                NULL as previous_revenue
            FROM {stats_subquery} as stats
            LEFT JOIN {conversion_subquery} as conversions
            """,
                placeholders={
                    "stats_subquery": stats_subquery,
                    "conversion_subquery": conversion_subquery,
                },
            ),
        )

        return query

    def _build_overview_conversion_subquery(self) -> ast.SelectQuery:
        """Build subquery that gets conversion counts from raw events table"""
        # Build the inner events query grouped by session
        inner_query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                session.session_id AS session_id,
                min(session.$start_timestamp) as start_timestamp,
                {conversion_count} as conversion_count,
                {conversion_person_id} as conversion_person_id
            FROM events
            WHERE and(
                {events_session_id} IS NOT NULL,
                {event_type_expr},
                {inside_timestamp_period},
                {all_properties}
            )
            GROUP BY session_id
            """,
                placeholders={
                    "conversion_count": self.runner.conversion_count_expr or ast.Constant(value=0),
                    "conversion_person_id": self.runner.conversion_person_id_expr or ast.Constant(value=None),
                    "events_session_id": self.runner.events_session_property,
                    "event_type_expr": self.runner.event_type_expr,
                    "inside_timestamp_period": self.runner._periods_expression("timestamp"),
                    "all_properties": property_to_expr(
                        self.runner.query.properties + self.runner._test_account_filters, team=self.runner.team
                    ),
                },
            ),
        )

        # Wrap in outer query that does period-based aggregation
        outer_query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                {total_conversions_current} AS total_conversions,
                {total_conversions_previous} AS previous_total_conversions,
                {unique_conversions_current} AS unique_conversions,
                {unique_conversions_previous} AS previous_unique_conversions
            FROM {inner_query}
            WHERE {inside_start_timestamp_period}
            """,
                placeholders={
                    "inner_query": inner_query,
                    "total_conversions_current": ast.Call(
                        name="sumIf",
                        args=[
                            ast.Field(chain=["conversion_count"]),
                            self.runner._current_period_expression("start_timestamp"),
                        ],
                    ),
                    "total_conversions_previous": (
                        ast.Call(
                            name="sumIf",
                            args=[
                                ast.Field(chain=["conversion_count"]),
                                self.runner._previous_period_expression("start_timestamp"),
                            ],
                        )
                        if self.runner.query_compare_to_date_range
                        else ast.Constant(value=0)
                    ),
                    "unique_conversions_current": ast.Call(
                        name="uniqIf",
                        args=[
                            ast.Field(chain=["conversion_person_id"]),
                            self.runner._current_period_expression("start_timestamp"),
                        ],
                    ),
                    "unique_conversions_previous": (
                        ast.Call(
                            name="uniqIf",
                            args=[
                                ast.Field(chain=["conversion_person_id"]),
                                self.runner._previous_period_expression("start_timestamp"),
                            ],
                        )
                        if self.runner.query_compare_to_date_range
                        else ast.Constant(value=0)
                    ),
                    "inside_start_timestamp_period": self.runner._periods_expression("start_timestamp"),
                },
            ),
        )

        return outer_query

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
