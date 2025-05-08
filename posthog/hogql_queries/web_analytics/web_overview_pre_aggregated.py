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
            
            # Build query with both current and previous period data using CTEs
            return self._build_comparison_query(
                team_id, 
                include_revenue,
                current_date_from, 
                current_date_to,
                previous_date_from,
                previous_date_to
            )
        else:
            # Build simpler query for current period only
            return self._build_single_period_query(
                team_id,
                include_revenue,
                current_date_from,
                current_date_to
            )
    
    def _build_comparison_query(
        self, 
        team_id: int, 
        include_revenue: bool, 
        current_date_from: str, 
        current_date_to: str,
        previous_date_from: str,
        previous_date_to: str
    ) -> ast.SelectQuery:
        """Build a query that compares current period with a previous period"""
        # Don't try to convert AST to string - build the where conditions directly as strings
        # Build simple where clauses as strings to avoid AST conversion issues
        current_where = f"team_id = {team_id} AND day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}'"
        previous_where = f"team_id = {team_id} AND day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}'"
        
        # Add property filters if needed
        property_filters = self._get_property_filter_sql()
        if property_filters:
            current_where += f" AND {property_filters}"
            previous_where += f" AND {property_filters}"
        
        # Use subqueries instead of CTEs
        query_str = f"""
        SELECT
            (SELECT uniqMerge(persons_uniq_state) FROM web_overview_daily WHERE {current_where}) AS unique_persons,
            (SELECT uniqMerge(persons_uniq_state) FROM web_overview_daily WHERE {previous_where}) AS previous_unique_persons,
            (SELECT sumMerge(pageviews_count_state) FROM web_overview_daily WHERE {current_where}) AS pageviews,
            (SELECT sumMerge(pageviews_count_state) FROM web_overview_daily WHERE {previous_where}) AS previous_pageviews,
            (SELECT uniqMerge(sessions_uniq_state) FROM web_overview_daily WHERE {current_where}) AS unique_sessions,
            (SELECT uniqMerge(sessions_uniq_state) FROM web_overview_daily WHERE {previous_where}) AS previous_unique_sessions,
            (SELECT
                if(
                    uniqMerge(sessions_uniq_state) > 0,
                    sumMerge(total_session_duration_state) / uniqMerge(sessions_uniq_state),
                    0
                )
             FROM web_overview_daily WHERE {current_where}) AS avg_session_duration,
            (SELECT
                if(
                    uniqMerge(sessions_uniq_state) > 0,
                    sumMerge(total_session_duration_state) / uniqMerge(sessions_uniq_state),
                    0
                )
             FROM web_overview_daily WHERE {previous_where}) AS previous_avg_session_duration,
            (SELECT
                if(
                    uniqMerge(sessions_uniq_state) > 0,
                    sumMerge(total_bounces_state) / uniqMerge(sessions_uniq_state),
                    0
                )
             FROM web_overview_daily WHERE {current_where}) AS bounce_rate,
            (SELECT
                if(
                    uniqMerge(sessions_uniq_state) > 0,
                    sumMerge(total_bounces_state) / uniqMerge(sessions_uniq_state),
                    0
                )
             FROM web_overview_daily WHERE {previous_where}) AS previous_bounce_rate,
            {0 if include_revenue else "NULL"} AS revenue,
            {0 if include_revenue else "NULL"} AS previous_revenue
        """
        
        return parse_select(query_str)
    
    def _build_single_period_query(
        self, 
        team_id: int, 
        include_revenue: bool, 
        date_from: str, 
        date_to: str
    ) -> ast.SelectQuery:
        """Build a query for a single period without comparison"""
        # Create a programmatic select list for better extensibility
        select_items = []
        
        # Add metric columns first
        metrics_select = self._get_metrics_select_expressions(include_revenue)
        select_items.extend(metrics_select)
        
        # Add NULL columns for previous period metrics to maintain consistent output format
        select_items.extend([
            ast.Alias(alias="previous_unique_persons", expr=ast.Constant(value=None)),
            ast.Alias(alias="previous_pageviews", expr=ast.Constant(value=None)),
            ast.Alias(alias="previous_unique_sessions", expr=ast.Constant(value=None)),
            ast.Alias(alias="previous_avg_session_duration", expr=ast.Constant(value=None)),
            ast.Alias(alias="previous_bounce_rate", expr=ast.Constant(value=None)),
            ast.Alias(alias="previous_revenue", expr=ast.Constant(value=None)),
        ])
        
        # Build the query
        select_query = ast.SelectQuery(
            select=select_items,
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["web_overview_daily"])
            ),
            where=self._build_where_clause(team_id, date_from, date_to)
        )
        
        return select_query
        
    def _get_metrics_select_expressions(self, include_revenue: bool) -> list[ast.Expr]:
        # Parse the metrics SQL into AST nodes for programmatic use
        metrics_sql = self._get_metrics_select_sql(include_revenue)
        metrics_query = parse_select(f"SELECT {metrics_sql}")
        
        return metrics_query.select
        
    def _build_where_clause(self, team_id: int, date_from: str, date_to: str) -> ast.Expr:
        conditions = [
            parse_expr(f"web_overview_daily.team_id = {team_id}"),
            parse_expr(f"web_overview_daily.day_bucket >= '{date_from}'"),
            parse_expr(f"web_overview_daily.day_bucket <= '{date_to}'"),
        ]
        
        property_filters = self._get_filters()
        if property_filters is not None:
            conditions.append(property_filters)
        
        if len(conditions) == 1:
            return conditions[0]
        
        return ast.Call(name="and", args=conditions)
    
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

    def _get_metrics_select_sql(self, include_revenue: bool) -> str:
        """Helper method to get the metrics SELECT part of the SQL query"""
        # Fix the revenue calculation to avoid reference to non-existent column
        return """
            uniqMerge(web_overview_daily.persons_uniq_state) AS unique_persons,
            sumMerge(web_overview_daily.pageviews_count_state) AS pageviews,
            uniqMerge(web_overview_daily.sessions_uniq_state) AS unique_sessions,
            if(
                uniqMerge(web_overview_daily.sessions_uniq_state) > 0,
                sumMerge(web_overview_daily.total_session_duration_state) / uniqMerge(web_overview_daily.sessions_uniq_state),
                0
            ) AS avg_session_duration,
            if(
                uniqMerge(web_overview_daily.sessions_uniq_state) > 0,
                sumMerge(web_overview_daily.total_bounces_state) / uniqMerge(web_overview_daily.sessions_uniq_state),
                0
            ) AS bounce_rate,
            {} AS revenue
        """.format("0" if include_revenue else "NULL")

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
                    filters.append(f"web_overview_daily.{field_name} = '{value.id}'")
                elif isinstance(value, str):
                    filters.append(f"web_overview_daily.{field_name} = '{value}'")
                elif isinstance(value, list):
                    # Build an IN expression for lists
                    values = []
                    for v in value:
                        if hasattr(v, "id"):
                            values.append(f"'{v.id}'")
                        else:
                            values.append(f"'{v}'")
                    value_list = ", ".join(values)
                    filters.append(f"web_overview_daily.{field_name} IN ({value_list})")
        
        return " AND ".join(filters) if filters else ""