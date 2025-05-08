from typing import Optional, TYPE_CHECKING, Tuple, List, Any
import logging

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.clickhouse.client import sync_execute

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
            logger.debug(
                "Not using pre-aggregated tables: conversion goal requires full event data",
                extra={"team_id": self.runner.team.pk}
            )
            return False
            
        # Only a few property filters are supported with pre-aggregated tables
        supported_props = {"$host", "$device_type"}
        for prop in self.runner.query.properties:
            if not hasattr(prop, "key") or prop.key not in supported_props:
                logger.debug(
                    f"Not using pre-aggregated tables: property filter not supported ({getattr(prop, 'key', 'unknown')})",
                    extra={"team_id": self.runner.team.pk}
                )
                return False
        
        logger.info(
            "Using pre-aggregated tables for web overview query", 
            extra={"team_id": self.runner.team.pk}
        )
        return True
        
    def get_results(self) -> List[Tuple[Any, ...]]:
        """Execute query against pre-aggregated tables directly with ClickHouse and return results"""
        has_comparison = bool(self.runner.query_compare_to_date_range)
        include_revenue = self.runner.query.includeRevenue
        team_id = self.runner.team.pk
        
        logger.info(
            "Building simplified pre-aggregated query for web overview", 
            extra={
                "team_id": team_id,
                "has_comparison": has_comparison,
                "include_revenue": include_revenue
            }
        )
        
        # Get date ranges and format them for ClickHouse compatibility
        date_from = self.runner.query_date_range.date_from()
        date_to = self.runner.query_date_range.date_to()
        
        # Convert to simple YYYY-MM-DD format that ClickHouse accepts
        current_date_from = date_from.strftime('%Y-%m-%d')
        current_date_to = date_to.strftime('%Y-%m-%d')
        
        # Build WHERE conditions
        where_conditions = [f"team_id = {team_id}", f"day_bucket >= '{current_date_from}'", f"day_bucket <= '{current_date_to}'"]
        
        # Add property filters
        field_mapping = {
            "$host": "host",
            "$device_type": "device_type",
        }
        
        for p in self.runner.query.properties:
            if hasattr(p, "key") and p.key in field_mapping and hasattr(p, "value"):
                field_name = field_mapping[p.key]
                if isinstance(p.value, str):
                    where_conditions.append(f"{field_name} = '{p.value}'")
                elif isinstance(p.value, list):
                    values = ", ".join([f"'{v}'" for v in p.value])
                    where_conditions.append(f"{field_name} IN ({values})")
        
        # Combine WHERE conditions
        where_clause = " AND ".join(where_conditions)
        
        # Important: We need to structure the query results to match exactly what web_overview.calculate expects
        # Build the SQL query, using aliases that match the structure expected by the calculate method
        sql = f"""
SELECT 
    uniqMerge(persons_uniq_state) as unique_persons,
    NULL as previous_unique_persons,
    sumMerge(pageviews_count_state) as pageviews,
    NULL as previous_pageviews,
    uniqMerge(sessions_uniq_state) as unique_sessions,
    NULL as previous_unique_sessions,
    if(uniqMerge(sessions_uniq_state) > 0, sumMerge(total_session_duration_state) / uniqMerge(sessions_uniq_state), 0) as avg_session_duration,
    NULL as previous_avg_session_duration,
    if(uniqMerge(sessions_uniq_state) > 0, sumMerge(total_bounces_state) / uniqMerge(sessions_uniq_state), 0) as bounce_rate,
    NULL as previous_bounce_rate,
    {0 if include_revenue else 'NULL'} as revenue,
    NULL as previous_revenue
FROM web_overview_daily
WHERE {where_clause}
"""
        
        logger.info(
            "Executing ClickHouse SQL query directly", 
            extra={
                "team_id": team_id,
                "sql": sql
            }
        )

        logger.debug(
            sql, 
            extra={
                "team_id": team_id,
            }
        )
        
        try:
            # Execute the query directly with ClickHouse
            results = sync_execute(sql)
            
            logger.debug(
                "Successfully executed ClickHouse query", 
                extra={
                    "team_id": team_id,
                    "result_count": len(results) if results else 0
                }
            )
            
            # If there are no results, return an empty row to avoid errors
            if not results or not results[0]:
                results = [(0, None, 0, None, 0, None, 0, None, 0, None, 0 if include_revenue else None, None)]
            
            return results
            
        except Exception as e:
            logger.exception(
                "Error executing ClickHouse query", 
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