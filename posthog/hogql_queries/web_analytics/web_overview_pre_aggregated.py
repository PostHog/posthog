from typing import TYPE_CHECKING, Optional
from datetime import datetime, UTC, timedelta

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.pre_aggregated.properties import WEB_OVERVIEW_SUPPORTED_PROPERTIES
from posthog.hogql.transforms.state_aggregations import combine_queries_with_state_and_merge

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner


class WebOverviewPreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    def __init__(self, runner: "WebOverviewQueryRunner") -> None:
        super().__init__(runner, supported_props_filters=WEB_OVERVIEW_SUPPORTED_PROPERTIES)

    def can_combine_with_realtime_data(self) -> bool:
        """
        Check if we can combine pre-aggregated data with real-time data.
        This is more lenient than can_use_preaggregated_tables() because it allows current day data.
        """
        query = self.runner.query

        # Check if properties are supported
        for prop in query.properties:
            if hasattr(prop, "key") and prop.key not in self.supported_props_filters:
                return False

        # Don't support conversion goals yet
        if query.conversionGoal:
            return False

        return True

    def get_combined_query(self) -> ast.SelectQuery:
        """
        Create a combined query that uses pre-aggregated data for historical dates
        and real-time data for current day, combined using state/merge functions.
        """
        today = datetime.now(UTC).date()

        # Split date ranges
        historical_date_to = min(self.runner.query_date_range.date_to().date(), today - timedelta(days=1))
        current_day_date_from = max(self.runner.query_date_range.date_from().date(), today)

        queries_to_combine = []

        # Add historical data query if there's historical data to query
        if self.runner.query_date_range.date_from().date() <= historical_date_to:
            historical_query = self._get_historical_query_string(historical_date_to)
            queries_to_combine.append(historical_query)

        # Add current day query if current day is in the range
        if current_day_date_from <= self.runner.query_date_range.date_to().date():
            current_day_query = self._get_current_day_query_string(current_day_date_from)
            queries_to_combine.append(current_day_query)

        # If we only have one query, no need to combine
        if len(queries_to_combine) == 1:
            # Transform the single query to use state aggregations and merge
            return combine_queries_with_state_and_merge(queries_to_combine[0])
        elif len(queries_to_combine) > 1:
            # Combine multiple queries
            return combine_queries_with_state_and_merge(*queries_to_combine)
        else:
            # Fallback to regular query if no data ranges match
            return self.runner.outer_select

    def _get_historical_query_string(self, date_to) -> str:
        """Get the pre-aggregated query for historical data as a HogQL string."""
        # Create a temporary query builder with modified date range
        # We'll manually create the filters with the adjusted dates
        previous_period_filter, current_period_filter = self._get_custom_date_ranges(historical_date_to=date_to)

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

        # Add WHERE filters for the historical date range and any property filters
        filters = self._get_historical_filters(date_to)
        if filters:
            query.where = filters

        # Convert to string
        context = HogQLContext(team_id=self.runner.team.pk, enable_select_queries=True)
        query_string = print_ast(query, context, "hogql")

        return query_string

    def _get_current_day_query_string(self, date_from) -> str:
        """Get the regular query for current day data as a HogQL string."""
        # Create a modified version of the outer_select query with adjusted date range
        # We'll inject custom date expressions
        has_comparison = bool(self.runner.query_compare_to_date_range)

        def current_period_aggregate(
            function_name: str,
            column_name: str,
            alias: str,
            params: Optional[list[ast.Expr]] = None,
        ):
            if not has_comparison:
                return ast.Alias(
                    alias=alias, expr=ast.Call(name=function_name, params=params, args=[ast.Field(chain=[column_name])])
                )

            # Use custom date range for current day only
            current_day_start = ast.Constant(
                value=datetime.combine(date_from, datetime.min.time()).replace(
                    tzinfo=self.runner.query_date_range._timezone_info
                )
            )
            current_day_end = ast.Constant(value=self.runner.query_date_range.date_to())

            return self.runner.period_aggregate(
                function_name,
                column_name,
                current_day_start,
                current_day_end,
                alias=alias,
                params=params,
            )

        def previous_period_aggregate(
            function_name: str,
            column_name: str,
            alias: str,
            params: Optional[list[ast.Expr]] = None,
        ):
            if not has_comparison:
                return ast.Alias(alias=alias, expr=ast.Constant(value=None))

            # For current day queries, we might not have previous period data
            # But we'll use the original comparison date range
            return self.runner.period_aggregate(
                function_name,
                column_name,
                self.runner.query_compare_to_date_range.date_from_as_hogql(),
                self.runner.query_compare_to_date_range.date_to_as_hogql(),
                alias=alias,
                params=params,
            )

        def metric_pair(
            function_name: str,
            column_name: str,
            current_alias: str,
            previous_alias: Optional[str] = None,
            params: Optional[list[ast.Expr]] = None,
        ) -> list[ast.Expr]:
            previous_alias = previous_alias or f"previous_{current_alias}"
            return [
                current_period_aggregate(function_name, column_name, current_alias, params),
                previous_period_aggregate(function_name, column_name, previous_alias, params),
            ]

        select: list[ast.Expr] = []

        if self.runner.query.conversionGoal:
            # Add standard conversion goal metrics
            select.extend(metric_pair("uniq", "session_person_id", "unique_users"))
            select.extend(metric_pair("sum", "conversion_count", "total_conversion_count"))
            select.extend(metric_pair("uniq", "conversion_person_id", "unique_conversions"))

            conversion_rate = ast.Alias(
                alias="conversion_rate",
                expr=ast.Call(
                    name="divide",
                    args=[
                        ast.Field(chain=["unique_conversions"]),
                        ast.Field(chain=["unique_users"]),
                    ],
                ),
            )

            previous_conversion_rate = ast.Alias(
                alias="previous_conversion_rate",
                expr=(
                    ast.Constant(value=None)
                    if not has_comparison
                    else ast.Call(
                        name="divide",
                        args=[
                            ast.Field(chain=["previous_unique_conversions"]),
                            ast.Field(chain=["previous_unique_users"]),
                        ],
                    )
                ),
            )

            select.extend([conversion_rate, previous_conversion_rate])

            if self.runner.query.includeRevenue:
                select.extend(metric_pair("sum", "session_conversion_revenue", "conversion_revenue"))

        else:
            select.extend(metric_pair("uniq", "session_person_id", "unique_users"))
            select.extend(metric_pair("sum", "filtered_pageview_count", "total_filtered_pageview_count"))
            select.extend(metric_pair("uniq", "session_id", "unique_sessions"))
            select.extend(metric_pair("avg", "session_duration", "avg_duration_s"))
            select.extend(metric_pair("avg", "is_bounce", "bounce_rate"))

            if self.runner.query.includeRevenue:
                select.extend(metric_pair("sum", "session_revenue", "revenue"))

        # Create the inner select query with current day filtering
        inner_select = self._get_current_day_inner_select(date_from)

        query = ast.SelectQuery(select=select, select_from=ast.JoinExpr(table=inner_select))

        # Convert to string
        context = HogQLContext(team_id=self.runner.team.pk, enable_select_queries=True)
        query_string = print_ast(query, context, "hogql")

        return query_string

    def _get_custom_date_ranges(self, historical_date_to) -> tuple[ast.Expr, ast.Expr]:
        """Get custom date ranges for historical data only."""
        # Adjust the current period filter to exclude current day
        historical_date_from = self.runner.query_date_range.date_from()
        historical_end = datetime.combine(historical_date_to, datetime.max.time()).replace(
            tzinfo=self.runner.query_date_range._timezone_info
        )

        current_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["day_bucket"]),
                    right=ast.Constant(value=historical_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["day_bucket"]),
                    right=ast.Constant(value=historical_end),
                ),
            ]
        )

        # For previous period, use the original comparison range if it exists
        if self.runner.query_compare_to_date_range:
            previous_date_from = self.runner.query_compare_to_date_range.date_from()
            previous_date_to = self.runner.query_compare_to_date_range.date_to()
        else:
            previous_date_from = historical_date_from
            previous_date_to = historical_end

        previous_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["day_bucket"]),
                    right=ast.Constant(value=previous_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["day_bucket"]),
                    right=ast.Constant(value=previous_date_to),
                ),
            ]
        )

        return (previous_period_filter, current_period_filter)

    def _get_historical_filters(self, date_to) -> ast.Expr:
        """Get filters for historical pre-aggregated data."""
        historical_date_from = self.runner.query_date_range.date_from()
        historical_end = datetime.combine(date_to, datetime.max.time()).replace(
            tzinfo=self.runner.query_date_range._timezone_info
        )

        filter_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["web_bounces_daily", "day_bucket"]),
                right=ast.Constant(value=historical_date_from),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["web_bounces_daily", "day_bucket"]),
                right=ast.Constant(value=historical_end),
            ),
        ]

        # Add property filters if any
        if self.runner.query.properties:
            supported_properties = [
                prop
                for prop in self.runner.query.properties
                if hasattr(prop, "key") and prop.key in self.supported_props_filters
            ]

            if supported_properties:
                from posthog.hogql_queries.web_analytics.pre_aggregated.property_transformer import (
                    PreAggregatedPropertyTransformer,
                )

                property_expr = property_to_expr(supported_properties, self.runner.team)
                transformer = PreAggregatedPropertyTransformer("web_bounces_daily", self.supported_props_filters)
                transformed_expr = transformer.visit(property_expr)
                filter_exprs.append(transformed_expr)

        return ast.And(exprs=filter_exprs) if len(filter_exprs) > 1 else filter_exprs[0]

    def _get_current_day_inner_select(self, date_from) -> ast.SelectQuery:
        """Get the inner select query for current day data."""
        # Create a modified version of the inner_select with current day date filtering
        parsed_select = parse_select(
            """
SELECT
    any(events.person_id) as session_person_id,
    session.session_id as session_id,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and(
    {events_session_id} IS NOT NULL,
    {event_type_expr},
    {current_day_timestamp_filter},
    {all_properties},
)
GROUP BY session_id
HAVING {current_day_start_timestamp_filter}
        """,
            placeholders={
                "all_properties": self.runner.all_properties(),
                "event_type_expr": self.runner.event_type_expr,
                "current_day_timestamp_filter": self._get_current_day_timestamp_filter(date_from),
                "current_day_start_timestamp_filter": self._get_current_day_start_timestamp_filter(date_from),
                "events_session_id": self.runner.events_session_property,
            },
        )
        assert isinstance(parsed_select, ast.SelectQuery)

        if self.runner.conversion_count_expr and self.runner.conversion_person_id_expr:
            parsed_select.select.append(ast.Alias(alias="conversion_count", expr=self.runner.conversion_count_expr))
            parsed_select.select.append(
                ast.Alias(alias="conversion_person_id", expr=self.runner.conversion_person_id_expr)
            )
            if self.runner.query.includeRevenue:
                parsed_select.select.append(
                    ast.Alias(alias="session_conversion_revenue", expr=self.runner.conversion_revenue_expr)
                )
        else:
            parsed_select.select.append(
                ast.Alias(
                    alias="session_duration",
                    expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$session_duration"])]),
                )
            )
            parsed_select.select.append(
                ast.Alias(alias="filtered_pageview_count", expr=self.runner.pageview_count_expression)
            )
            parsed_select.select.append(
                ast.Alias(
                    alias="is_bounce", expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$is_bounce"])])
                )
            )
            if self.runner.query.includeRevenue:
                from posthog.hogql.database.schema.exchange_rate import revenue_sum_expression_for_events

                parsed_select.select.append(
                    ast.Alias(
                        alias="session_revenue",
                        expr=revenue_sum_expression_for_events(self.runner.team.revenue_analytics_config),
                    )
                )

        return parsed_select

    def _get_current_day_timestamp_filter(self, date_from) -> ast.Expr:
        """Get timestamp filter for current day events."""
        current_day_start = datetime.combine(date_from, datetime.min.time()).replace(
            tzinfo=self.runner.query_date_range._timezone_info
        )
        current_day_end = self.runner.query_date_range.date_to()

        return ast.Call(
            name="and",
            args=[
                ast.CompareOperation(
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=current_day_start),
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=current_day_end),
                    op=ast.CompareOperationOp.LtEq,
                ),
            ],
        )

    def _get_current_day_start_timestamp_filter(self, date_from) -> ast.Expr:
        """Get start timestamp filter for current day sessions."""
        current_day_start = datetime.combine(date_from, datetime.min.time()).replace(
            tzinfo=self.runner.query_date_range._timezone_info
        )

        return ast.CompareOperation(
            left=ast.Field(chain=["start_timestamp"]),
            right=ast.Constant(value=current_day_start),
            op=ast.CompareOperationOp.GtEq,
        )

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
