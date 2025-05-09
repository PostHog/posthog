from typing import TYPE_CHECKING
import logging

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

logger = logging.getLogger(__name__)


class WebOverviewPreAggregatedQueryBuilder:
    """Builder for pre-aggregated table queries for web overview metrics."""
    
    def __init__(self, runner: "WebOverviewQueryRunner") -> None:
        self.runner = runner
        
    def can_use_preaggregated_tables(self) -> bool:
        """
        Determines if pre-aggregated tables can be used for this query.
        
        Returns:
            bool: True if pre-aggregated tables can be used, False otherwise.
        """
        query = self.runner.query
        
        # Only works for properties we know are in pre-aggregated tables
        for prop in query.properties:
            if hasattr(prop, "key") and prop.key not in {"$host", "$device_type"}:
                return False
        
        # If there's a conversion goal, we need standard query for attribution
        if query.conversionGoal:
            return False
                    
        # Otherwise we're good to go!
        return True  
        
    def get_query(self) -> ast.SelectQuery:
        """Build and return a HogQL query for pre-aggregated table data"""
        # Generate IDs, date ranges, team ID
        team_id = self.runner.team.pk
        include_revenue = self.runner.query.includeRevenue
        
        # Format date ranges for clickhouse
        current_date_from = self.runner.query_date_range.date_from().strftime("%Y-%m-%d")
        current_date_to = self.runner.query_date_range.date_to().strftime("%Y-%m-%d")
        
        # Log parameters we're using
        logger.info(
            "Pre-aggregated web overview query",
            extra={
                "team_id": team_id,
                "include_revenue": include_revenue,
                "date_from": current_date_from,
                "date_to": current_date_to,
            },
        )
        
        # Check if we have a previous period to compare with
        has_previous_period = bool(self.runner.query_compare_to_date_range)
        
        if has_previous_period:
            previous_date_from = self.runner.query_compare_to_date_range.date_from().strftime("%Y-%m-%d")
            previous_date_to = self.runner.query_compare_to_date_range.date_to().strftime("%Y-%m-%d")
            
            logger.info(
                "Including previous period comparison",
                extra={
                    "previous_date_from": previous_date_from,
                    "previous_date_to": previous_date_to,
                },
            )
        else:
            # Use same date range for previous period to get NULLs via empty results
            previous_date_from = current_date_from 
            previous_date_to = current_date_from  # Using same date will result in empty comparison
        
        # Always use comparison query
        return self._build_comparison_query(
            team_id, 
            include_revenue,
            current_date_from, 
            current_date_to,
            previous_date_from,
            previous_date_to
        )
    
    def _build_comparison_query(
        self, 
        current_date_from: str, 
        current_date_to: str,
        previous_date_from: str,
        previous_date_to: str
    ) -> ast.SelectQuery:
        """Build a query that compares current period with a previous period using conditional aggregation"""
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
        
        # Add property filters if needed
        property_filters = self._get_property_filter_sql()
        if property_filters:
            query_str += f" AND {property_filters}"
            
        return parse_select(query_str)
    
    def _get_filters(self) -> ast.Expr:
        # Map from PostHog property keys to pre-aggregated table field names.
        field_mapping = {
            "$host": "host",
            "$device_type": "device_type",
        }
        
        filters = []
        
        for p in self.runner.query.properties:
            if hasattr(p, "key") and p.key in field_mapping:
                field_name = field_mapping[p.key]
                
                # Get property value based on property type
                if hasattr(p, "value"):
                    value = p.value
                else:
                    # Skip properties without values
                    continue
                
                if hasattr(value, "id"):
                    # Use the id attribute as the value for objects
                    filters.append(parse_expr(f"web_overview_daily.{field_name} = '{value.id}'"))
                elif isinstance(value, str):
                    filters.append(parse_expr(f"web_overview_daily.{field_name} = '{value}'"))
                elif isinstance(value, list):
                    # Build an IN expression for lists
                    values = []
                    for v in value:
                        if hasattr(v, "id"):
                            values.append(f"'{v.id}'")
                        else:
                            values.append(f"'{v}'")
                    value_list = ", ".join(values)
                    filters.append(parse_expr(f"web_overview_daily.{field_name} IN ({value_list})"))
        
        if not filters:
            return None
        
        if len(filters) == 1:
            return filters[0]
        
        return ast.Call(name="and", args=filters)

    def _get_property_filter_sql(self) -> str:
        """Generate SQL filter expressions for properties"""
        # Map from PostHog property keys to pre-aggregated table field names
        field_mapping = {
            "$host": "host",
            "$device_type": "device_type",
        }
        
        filters = []
        
        for p in self.runner.query.properties:
            if hasattr(p, "key") and p.key in field_mapping:
                field_name = field_mapping[p.key]
                
                # Get property value based on property type
                if hasattr(p, "value"):
                    value = p.value
                else:
                    # Skip properties without values
                    continue
                
                if hasattr(value, "id"):
                    # Use the id attribute as the value for objects
                    filters.append(f"{field_name} = '{value.id}'")
                elif isinstance(value, str):
                    filters.append(f"{field_name} = '{value}'")
                elif isinstance(value, list):
                    # Build an IN expression for lists
                    values = []
                    for v in value:
                        if hasattr(v, "id"):
                            values.append(f"'{v.id}'")
                        else:
                            values.append(f"'{v}'")
                    value_list = ", ".join(values)
                    filters.append(f"{field_name} IN ({value_list})")
        
        return " AND ".join(filters) if filters else ""