from typing import TYPE_CHECKING, cast
from datetime import datetime, UTC

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner


class WebOverviewPreAggregatedQueryBuilder:
    # Supported property keys and their mapping to pre-aggregated table fields
    SUPPORTED_PROPERTIES = {
        "$host": "host",
        "$device_type": "device_type",
    }

    def __init__(self, runner: "WebOverviewQueryRunner") -> None:
        self.runner = runner

    def can_use_preaggregated_tables(self) -> bool:
        query = self.runner.query

        # Only works for properties we know are in the pre-aggregated tables
        for prop in query.properties:
            if hasattr(prop, "key") and prop.key not in self.SUPPORTED_PROPERTIES:
                return False

        if query.conversionGoal:
            return False

        # Only work for fixed-dates that don't include current-date in the filters.
        today = datetime.now(UTC).date()
        if self.runner.query_date_range.date_to().date() >= today:
            return False

        return True

    def get_query(self) -> ast.SelectQuery:
        current_date_from = self.runner.query_date_range.date_from_str
        current_date_to = self.runner.query_date_range.date_to_str

        # Handle previous period
        if self.runner.query_compare_to_date_range:
            previous_date_from = self.runner.query_compare_to_date_range.date_from_str
            previous_date_to = self.runner.query_compare_to_date_range.date_to_str
        else:
            # If we don't have a previous period, we can just use the same data as the values won't be used
            # and our query stays simpler.
            previous_date_from = current_date_from
            previous_date_to = current_date_from

        # Define date filter conditions first
        current_period_filter = f"day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}'"
        previous_period_filter = f"day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}'"

        # Define common query patterns for averages over sessions
        def safe_avg_calc(metric, period_filter):
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

            {safe_avg_calc("total_session_duration", current_period_filter)} AS avg_session_duration,
            {safe_avg_calc("total_session_duration", previous_period_filter)} AS previous_avg_session_duration,

            {safe_avg_calc("total_bounces", current_period_filter)} AS bounce_rate,
            {safe_avg_calc("total_bounces", previous_period_filter)} AS previous_bounce_rate,

            NULL AS revenue,
            NULL AS previous_revenue
        FROM web_overview_daily
        """

        query = cast(ast.SelectQuery, parse_select(query_str))

        filters = self._get_filters()
        if filters:
            query.where = filters

        return query

    # We can probably use the hogql general filters somehow but it was not working by default and it was a lot of moving parts to debug at once so
    # TODO: come back to this later to make sure we're not overcomplicating things
    def _get_filters(self):
        """Generate property filters for pre-aggregated tables"""
        if not self.runner.query.properties:
            return None

        # Build filter expressions
        filter_parts = []

        # Only process properties that we know how to map to pre-aggregated tables
        for posthog_field, table_field in self.SUPPORTED_PROPERTIES.items():
            for prop in self.runner.query.properties:
                if hasattr(prop, "key") and prop.key == posthog_field and hasattr(prop, "value"):
                    value = prop.value

                    # Extract ID if present
                    if value is not None and hasattr(value, "id"):
                        value = value.id

                    # The device_type input differs between "Desktop" | ["Mobile", "Tablet"]
                    if isinstance(value, list):
                        values = [v.id if v is not None and hasattr(v, "id") else v for v in value]
                        filter_expr = ast.CompareOperation(
                            op=ast.CompareOperationOp.In,
                            left=ast.Field(chain=["web_overview_daily", table_field]),
                            right=ast.Tuple(exprs=[ast.Constant(value=v) for v in values]),
                        )

                        filter_parts.append(filter_expr)
                    else:
                        filter_expr = ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["web_overview_daily", table_field]),
                            right=ast.Constant(value=value),
                        )

                        filter_parts.append(filter_expr)

        # If we have multiple filters, combine with AND
        if len(filter_parts) > 1:
            return ast.Call(name="and", args=cast(list[ast.Expr], filter_parts))
        elif len(filter_parts) == 1:
            return filter_parts[0]

        return None
