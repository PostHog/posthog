from typing import TYPE_CHECKING
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
            logger.debug(
                "Not using pre-aggregated tables: conversion goal requires full event data",
                extra={"team_id": self.runner.team.pk},
            )
            return False
            
        # Only a few property filters are supported with pre-aggregated tables
        supported_props = {"$host", "$device_type"}
        for prop in self.runner.query.properties:
            if not hasattr(prop, "key") or prop.key not in supported_props:
                logger.debug(
                    f"Not using pre-aggregated tables: property filter not supported ({getattr(prop, 'key', 'unknown')})",
                    extra={"team_id": self.runner.team.pk},
                )
                return False
        
        logger.info("Using pre-aggregated tables for web overview query", extra={"team_id": self.runner.team.pk})
        return True
        
    def get_query(self) -> ast.SelectQuery:
        """Build and return a HogQL query for pre-aggregated table data"""
        include_revenue = self.runner.query.includeRevenue
        team_id = self.runner.team.pk
        
        logger.info(
            "Building pre-aggregated query for web overview",
            extra={"team_id": team_id, "include_revenue": include_revenue},
        )
        
        # Get date ranges and format them for ClickHouse compatibility
        date_from = self.runner.query_date_range.date_from()
        date_to = self.runner.query_date_range.date_to()
        
        # Convert to simple YYYY-MM-DD format
        current_date_from = date_from.strftime("%Y-%m-%d")
        current_date_to = date_to.strftime("%Y-%m-%d")
        
        # Build the HogQL query using parse_select
        select_query = parse_select(
            """
            SELECT
                uniqMerge(web_overview_daily.persons_uniq_state) AS unique_persons,
                NULL AS previous_unique_persons,
                sumMerge(web_overview_daily.pageviews_count_state) AS pageviews,
                NULL AS previous_pageviews,
                uniqMerge(web_overview_daily.sessions_uniq_state) AS unique_sessions,
                NULL AS previous_unique_sessions,
                if(
                    uniqMerge(web_overview_daily.sessions_uniq_state) > 0,
                    sumMerge(web_overview_daily.total_session_duration_state) / uniqMerge(web_overview_daily.sessions_uniq_state),
                    0
                ) AS avg_session_duration,
                NULL AS previous_avg_session_duration,
                if(
                    uniqMerge(web_overview_daily.sessions_uniq_state) > 0,
                    sumMerge(web_overview_daily.total_bounces_state) / uniqMerge(web_overview_daily.sessions_uniq_state),
                    0
                ) AS bounce_rate,
                NULL AS previous_bounce_rate,
                {revenue_value} AS revenue,
                NULL AS previous_revenue
            FROM web_overview_daily
            WHERE {where_clause}
            """,
            placeholders={
                "revenue_value": ast.Constant(value=0 if include_revenue else None),
                "where_clause": self._build_where_clause(team_id, current_date_from, current_date_to),
            },
        )
        
        return select_query
        
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
        """Generate filter expressions for pre-aggregated tables"""
        # Map from PostHog property keys to pre-aggregated table field names.
        field_mapping = {
            "$host": "host",
            "$device_type": "device_type",
        }
        
        filters = []
        
        for p in self.runner.query.properties:
            if hasattr(p, "key") and p.key in field_mapping:
                field_name = field_mapping[p.key]
                value = p.value
                
                if hasattr(value, "id"):
                    # Use the id attribute as the value for objects
                    filters.append(parse_expr(f"web_overview_daily.{field_name} = '{value.id}'"))
                elif isinstance(value, str):
                    filters.append(parse_expr(f"web_overview_daily.{field_name} = '{value}'"))
                elif isinstance(value, list):
                    value_list = ", ".join([f"'{v.id if hasattr(v, 'id') else v}'" for v in value])
                    filters.append(parse_expr(f"web_overview_daily.{field_name} IN ({value_list})"))
        
        if not filters:
            return None
        
        if len(filters) == 1:
            return filters[0]
        
        return ast.Call(name="and", args=filters)
