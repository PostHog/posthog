from typing import TYPE_CHECKING
import logging

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

logger = logging.getLogger(__name__)


class WebOverviewPreAggregatedQueryBuilder:
    """Builder for pre-aggregated table queries for web overview metrics."""

    # Supported property keys and their mapping to pre-aggregated table fields
    SUPPORTED_PROPERTIES = {
        "$host": "host",
        "$device_type": "device_type",
    }

    def __init__(self, runner: "WebOverviewQueryRunner") -> None:
        self.runner = runner

    def can_use_preaggregated_tables(self) -> bool:
        query = self.runner.query

        # Only works for properties we know are in pre-aggregated tables
        for prop in query.properties:
            if hasattr(prop, "key") and prop.key not in self.SUPPORTED_PROPERTIES:
                return False

        # If there's a conversion goal, we need standard query for attribution
        if query.conversionGoal:
            return False

        return True

    def get_query(self) -> ast.SelectQuery:
        """Build and return a HogQL query for pre-aggregated table data"""
        # Always use comparison query
        return self._build_comparison_query()

    def _build_comparison_query(self) -> ast.SelectQuery:
        """Build a query that compares current period with a previous period using conditional aggregation"""
        # Get dates from class properties
        current_date_from = self.runner.query_date_range.date_from().strftime("%Y-%m-%d")
        current_date_to = self.runner.query_date_range.date_to().strftime("%Y-%m-%d")

        # Handle previous period
        if self.runner.query_compare_to_date_range:
            previous_date_from = self.runner.query_compare_to_date_range.date_from().strftime("%Y-%m-%d")
            previous_date_to = self.runner.query_compare_to_date_range.date_to().strftime("%Y-%m-%d")
        else:
            # Use same date for empty comparison
            previous_date_from = current_date_from
            previous_date_to = current_date_from

        # Build the query directly with conditional aggregation
        query_str = f"""
        SELECT
            uniqMergeIf(persons_uniq_state, day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}') AS unique_persons,
            uniqMergeIf(persons_uniq_state, day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}') AS previous_unique_persons,

            sumMergeIf(pageviews_count_state, day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}') AS pageviews,
            sumMergeIf(pageviews_count_state, day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}') AS previous_pageviews,

            uniqMergeIf(sessions_uniq_state, day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}') AS unique_sessions,
            uniqMergeIf(sessions_uniq_state, day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}') AS previous_unique_sessions,

            if(
                uniqMergeIf(sessions_uniq_state, day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}') > 0,
                sumMergeIf(total_session_duration_state, day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}') /
                uniqMergeIf(sessions_uniq_state, day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}'),
                0
            ) AS avg_session_duration,

            if(
                uniqMergeIf(sessions_uniq_state, day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}') > 0,
                sumMergeIf(total_session_duration_state, day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}') /
                uniqMergeIf(sessions_uniq_state, day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}'),
                0
            ) AS previous_avg_session_duration,

            if(
                uniqMergeIf(sessions_uniq_state, day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}') > 0,
                sumMergeIf(total_bounces_state, day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}') /
                uniqMergeIf(sessions_uniq_state, day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}'),
                0
            ) AS bounce_rate,

            if(
                uniqMergeIf(sessions_uniq_state, day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}') > 0,
                sumMergeIf(total_bounces_state, day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}') /
                uniqMergeIf(sessions_uniq_state, day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}'),
                0
            ) AS previous_bounce_rate,

            NULL AS revenue,
            NULL AS previous_revenue
        FROM web_overview_daily
        """

        # Parse the select statement
        query = parse_select(query_str)

        # Add property filters if needed
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
            # Find properties matching this field
            for prop in self.runner.query.properties:
                if hasattr(prop, "key") and prop.key == posthog_field and hasattr(prop, "value"):
                    value = prop.value

                    # Extract ID if present
                    if hasattr(value, "id"):
                        value = value.id

                    # Build expression based on value type
                    if isinstance(value, list):
                        # Extract IDs from list items if needed
                        values = [v.id if hasattr(v, "id") else v for v in value]

                        # Create a tuple of constants for IN expression
                        tuple_elements = [ast.Constant(value=v) for v in values]
                        tuple_expr = ast.Tuple(exprs=tuple_elements)

                        # Create field reference
                        field_ref = ast.Field(chain=["web_overview_daily", table_field.strip("`")])

                        # Create IN expression
                        filter_expr = ast.CompareOperation(
                            op=ast.CompareOperationOp.In, left=field_ref, right=tuple_expr
                        )

                        filter_parts.append(filter_expr)
                    else:
                        # Create field reference
                        field_ref = ast.Field(chain=["web_overview_daily", table_field.strip("`")])

                        # Create equality expression
                        filter_expr = ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq, left=field_ref, right=ast.Constant(value=value)
                        )

                        filter_parts.append(filter_expr)

        # If we have multiple filters, combine with AND
        if len(filter_parts) > 1:
            return ast.Call(name="and", args=filter_parts)
        elif len(filter_parts) == 1:
            return filter_parts[0]

        return None
