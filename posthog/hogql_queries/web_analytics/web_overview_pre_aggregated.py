from typing import Optional, TYPE_CHECKING, Tuple, List, Any, Dict
import logging

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.database.models import (
    IntegerDatabaseField, 
    StringDatabaseField, 
    DateDatabaseField, 
    Table, 
    FieldOrTable
)

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

logger = logging.getLogger(__name__)

# Register merge state functions if they don't exist
if "uniqMerge" not in HOGQL_AGGREGATIONS:
    from posthog.hogql.functions import HogQLFunctionMeta
    from posthog.hogql.functions.types import UnknownType, FloatType
    
    HOGQL_AGGREGATIONS["uniqMerge"] = HogQLFunctionMeta("uniqMerge", 1, 1, aggregate=True)
    HOGQL_AGGREGATIONS["sumMerge"] = HogQLFunctionMeta("sumMerge", 1, 1, aggregate=True)


# Define the pre-aggregated table schema
class WebOverviewDailyTable(Table):
    fields: Dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "day_bucket": DateDatabaseField(name="day_bucket"),
        "host": StringDatabaseField(name="host", nullable=True),
        "device_type": StringDatabaseField(name="device_type", nullable=True),
        "persons_uniq_state": StringDatabaseField(name="persons_uniq_state"),
        "pageviews_count_state": StringDatabaseField(name="pageviews_count_state"),
        "sessions_uniq_state": StringDatabaseField(name="sessions_uniq_state"),
        "total_session_duration_state": StringDatabaseField(name="total_session_duration_state"),
        "total_bounces_state": StringDatabaseField(name="total_bounces_state")
    }
    
    def to_printed_clickhouse(self, context):
        return "web_overview_daily"
    
    def to_printed_hogql(self):
        return "web_overview_daily"


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
        """Execute query against pre-aggregated tables using HogQL and return results"""
        has_comparison = bool(self.runner.query_compare_to_date_range)
        include_revenue = self.runner.query.includeRevenue
        team_id = self.runner.team.pk
        
        logger.error(f"{team_id} {has_comparison} {include_revenue}")

        logger.error(
            "Building simplified pre-aggregated query for web overview using HogQL", 
            extra={
                "team_id": team_id,
                "has_comparison": has_comparison,
                "include_revenue": include_revenue
            }
        )
        
        # Get date ranges and format them for ClickHouse compatibility
        date_from = self.runner.query_date_range.date_from()
        date_to = self.runner.query_date_range.date_to()
        
        # Convert to simple YYYY-MM-DD format
        current_date_from = date_from.strftime('%Y-%m-%d')
        current_date_to = date_to.strftime('%Y-%m-%d')
        
        # Create the database and HogQL context
        context = HogQLContext(
            team_id=team_id,
            enable_select_queries=True,
            database=create_hogql_database(team_id=team_id),
        )
        
        # Add the web_overview_daily table to the database
        context.database.web_overview_daily = WebOverviewDailyTable()
        
        # Build the HogQL query
        select_query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="unique_persons",
                    expr=ast.Call(name="uniqMerge", args=[ast.Field(chain=["web_overview_daily", "persons_uniq_state"])])
                ),
                ast.Alias(
                    alias="previous_unique_persons",
                    expr=ast.Constant(value=None)
                ),
                ast.Alias(
                    alias="pageviews",
                    expr=ast.Call(name="sumMerge", args=[ast.Field(chain=["web_overview_daily", "pageviews_count_state"])])
                ),
                ast.Alias(
                    alias="previous_pageviews",
                    expr=ast.Constant(value=None)
                ),
                ast.Alias(
                    alias="unique_sessions",
                    expr=ast.Call(name="uniqMerge", args=[ast.Field(chain=["web_overview_daily", "sessions_uniq_state"])])
                ),
                ast.Alias(
                    alias="previous_unique_sessions",
                    expr=ast.Constant(value=None)
                ),
                ast.Alias(
                    alias="avg_session_duration",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                left=ast.Call(name="uniqMerge", args=[ast.Field(chain=["web_overview_daily", "sessions_uniq_state"])]),
                                op=ast.CompareOperationOp.Gt,
                                right=ast.Constant(value=0)
                            ),
                            ast.ArithmeticOperation(
                                left=ast.Call(name="sumMerge", args=[ast.Field(chain=["web_overview_daily", "total_session_duration_state"])]),
                                op=ast.ArithmeticOperationOp.Div,
                                right=ast.Call(name="uniqMerge", args=[ast.Field(chain=["web_overview_daily", "sessions_uniq_state"])])
                            ),
                            ast.Constant(value=0)
                        ]
                    )
                ),
                ast.Alias(
                    alias="previous_avg_session_duration",
                    expr=ast.Constant(value=None)
                ),
                ast.Alias(
                    alias="bounce_rate",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                left=ast.Call(name="uniqMerge", args=[ast.Field(chain=["web_overview_daily", "sessions_uniq_state"])]),
                                op=ast.CompareOperationOp.Gt,
                                right=ast.Constant(value=0)
                            ),
                            ast.ArithmeticOperation(
                                left=ast.Call(name="sumMerge", args=[ast.Field(chain=["web_overview_daily", "total_bounces_state"])]),
                                op=ast.ArithmeticOperationOp.Div,
                                right=ast.Call(name="uniqMerge", args=[ast.Field(chain=["web_overview_daily", "sessions_uniq_state"])])
                            ),
                            ast.Constant(value=0)
                        ]
                    )
                ),
                ast.Alias(
                    alias="previous_bounce_rate",
                    expr=ast.Constant(value=None)
                ),
                ast.Alias(
                    alias="revenue",
                    expr=ast.Constant(value=0 if include_revenue else None)
                ),
                ast.Alias(
                    alias="previous_revenue",
                    expr=ast.Constant(value=None)
                )
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["web_overview_daily"])),
            where=self._build_where_clause(team_id, current_date_from, current_date_to)
        )
        
        logger.info(
            "Executing HogQL query", 
            extra={
                "team_id": team_id,
            }
        )
        
        try:
            # Execute the HogQL query
            result = execute_hogql_query(
                query_type="hogql_query",
                query=select_query,
                team=self.runner.team,
                context=context
            )
            
            logger.debug(
                "Successfully executed HogQL query", 
                extra={
                    "team_id": team_id,
                    "result_count": len(result.results)
                }
            )
            
            # If there are no results, return an empty row to avoid errors
            if not result.results:
                return [(0, None, 0, None, 0, None, 0, None, 0, None, 0 if include_revenue else None, None)]
            
            return result.results
            
        except Exception as e:
            logger.exception(
                "Error executing HogQL query", 
                extra={
                    "team_id": team_id,
                    "error": str(e)
                }
            )
            raise
    
    def _build_where_clause(self, team_id: int, date_from: str, date_to: str) -> ast.Expr:
        """Build the WHERE clause for the HogQL query"""
        conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["web_overview_daily", "team_id"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=team_id)
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["web_overview_daily", "day_bucket"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Constant(value=date_from)
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["web_overview_daily", "day_bucket"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Constant(value=date_to)
            )
        ]
        
        property_filters = self._get_filters()
        if not isinstance(property_filters, ast.Constant) or property_filters.value != "":
            conditions.append(property_filters)
        
        if len(conditions) == 1:
            return conditions[0]
        
        return ast.Call(name="and", args=conditions)
    
    def _get_filters(self) -> ast.Expr:
        """Generate filter expressions for pre-aggregated tables"""
        # Map from PostHog property keys to pre-aggregated table field names
        field_mapping = {
            "$host": "host",
            "$device_type": "device_type",
        }
        
        filters = []
        
        logger.error(f"Filters: {self.runner.query.properties}")
        logger.error(f"================")
        logger.error(f"================")
        logger.error(f"================")

        for p in self.runner.query.properties:
            if hasattr(p, "key") and p.key in field_mapping:
                field_name = field_mapping[p.key]
                value = p.value
                
                # Handle case where value is an object with id attribute (like Team)
                if hasattr(value, 'id'):
                    # Use the id attribute as the value
                    filters.append(
                        ast.CompareOperation(
                            left=ast.Field(chain=["web_overview_daily", field_name]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value=value.id),
                        )
                    )
                elif isinstance(value, str):
                    filters.append(
                        ast.CompareOperation(
                            left=ast.Field(chain=["web_overview_daily", field_name]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value=value),
                        )
                    )
                elif isinstance(value, list):
                    filters.append(
                        ast.CompareOperation(
                            left=ast.Field(chain=["web_overview_daily", field_name]),
                            op=ast.CompareOperationOp.In,
                            right=ast.Tuple(exprs=[ast.Constant(value=v.id if hasattr(v, 'id') else v) for v in value]),
                        )
                    )
        
        if not filters:
            return ast.Constant(value="")
        
        if len(filters) == 1:
            return filters[0]
        
        return ast.Call(name="and", args=filters) 