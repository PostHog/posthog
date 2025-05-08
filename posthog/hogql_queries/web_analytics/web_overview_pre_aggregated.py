from typing import Optional, TYPE_CHECKING
import logging

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

logger = logging.getLogger(__name__)


class WebOverviewPreAggregatedQueryBuilder:
    """Builder for pre-aggregated table queries for web overview metrics."""
    
    def __init__(self, runner: "WebOverviewQueryRunner"):
        self.runner = runner
        
    def can_use_preaggregated_tables(self) -> bool:
        """Check if the current query can use pre-aggregated tables"""
        # Conversion goals require the full event data
        if self.runner.query.conversionGoal:
            logger.error(
                "Not using pre-aggregated tables: conversion goal requires full event data",
                extra={"team_id": self.runner.team.pk}
            )
            return False
            
        # Only a few property filters are supported with pre-aggregated tables
        supported_props = {"$host", "$device_type"}
        for prop in self.runner.query.properties:
            if not hasattr(prop, "key") or prop.key not in supported_props:
                logger.error(
                    f"Not using pre-aggregated tables: property filter not supported ({getattr(prop, 'key', 'unknown')})",
                    extra={"team_id": self.runner.team.pk}
                )
                return False
        
        logger.error(
            "Using pre-aggregated tables for web overview query", 
            extra={"team_id": self.runner.team.pk}
        )
        return True
        
    def build_query(self) -> ast.SelectQuery:
        """Build a query using pre-aggregated tables"""
        has_comparison = bool(self.runner.query_compare_to_date_range)
        include_revenue = self.runner.query.includeRevenue
        team_id = self.runner.team.pk
        
        logger.error(
            "Building simplified pre-aggregated query for web overview", 
            extra={
                "team_id": team_id,
                "has_comparison": has_comparison,
                "include_revenue": include_revenue
            }
        )
        
        # Get date ranges as strings instead of HogQL expressions
        current_date_from = str(self.runner.query_date_range.date_from)
        current_date_to = str(self.runner.query_date_range.date_to)
        
        # Very simplified query without any JOIN or comparison for now
        if include_revenue:
            revenue_expr = "0 as revenue"
        else:
            revenue_expr = "NULL as revenue"
                
        sql = f"""
SELECT
    uniqMerge(persons_uniq_state) as unique_persons,
    NULL as previous_unique_persons,
    sumMerge(pageviews_count_state) as pageviews,
    NULL as previous_pageviews,
    uniqMerge(sessions_uniq_state) as unique_sessions,
    NULL as previous_unique_sessions,
    if(unique_sessions > 0, sumMerge(total_session_duration_state) / unique_sessions, 0) as avg_session_duration,
    NULL as previous_avg_session_duration,
    if(unique_sessions > 0, sumMerge(total_bounces_state) / unique_sessions, 0) as bounce_rate,
    NULL as previous_bounce_rate,
    NULL as previous_revenue
FROM web_overview_daily
"""
        
        # Log the raw SQL for debugging
        logger.error(
            "Raw SQL query (no parsing)", 
            extra={
                "team_id": team_id,
                "sql": sql
            }
        )
        
        try:
            # Parse the SQL query directly without placeholders
            query = parse_select(sql)
            
            logger.debug(
                "Successfully parsed SQL query", 
                extra={
                    "team_id": team_id
                }
            )
            
            assert isinstance(query, ast.SelectQuery)
            return query
        except Exception as e:
            logger.exception(
                "Error parsing SQL query", 
                extra={
                    "team_id": team_id,
                    "sql": sql,
                    "error": str(e)
                }
            )
            raise
    
    def _get_filters(self) -> ast.Expr:
        """Generate filter expressions for pre-aggregated tables"""
        # Map from PostHog property keys to pre-aggregated table field names
        # TODO: Maybe we can standardize this somehow? 
        field_mapping = {
            "$host": "host",
            "$device_type": "device_type",
        }
        
        filters = []
        
        for p in self.runner.query.properties:
            if hasattr(p, "key") and p.key in field_mapping:
                field_name = field_mapping[p.key]
                value = p.value
                
                if isinstance(value, str):
                    filters.append(
                        ast.CompareOperation(
                            left=ast.Field(chain=[field_name]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value=value),
                        )
                    )
                elif isinstance(value, list):
                    filters.append(
                        ast.CompareOperation(
                            left=ast.Field(chain=[field_name]),
                            op=ast.CompareOperationOp.In,
                            right=ast.Tuple(exprs=[ast.Constant(value=v) for v in value]),
                        )
                    )
        
        if not filters:
            return ast.Constant(value="")
        
        if len(filters) == 1:
            return filters[0]
        
        return ast.Call(name="and", args=filters) 