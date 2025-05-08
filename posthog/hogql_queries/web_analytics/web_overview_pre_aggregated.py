from typing import TYPE_CHECKING, Any
import logging

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.database.models import (
    IntegerDatabaseField,
    StringDatabaseField,
    DateDatabaseField,
    Table,
    FieldOrTable,
)

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

logger = logging.getLogger(__name__)


# Define the pre-aggregated table schema
class WebOverviewDailyTable(Table):
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "day_bucket": DateDatabaseField(name="day_bucket"),
        "host": StringDatabaseField(name="host", nullable=True),
        "device_type": StringDatabaseField(name="device_type", nullable=True),
        "persons_uniq_state": StringDatabaseField(name="persons_uniq_state"),
        "pageviews_count_state": StringDatabaseField(name="pageviews_count_state"),
        "sessions_uniq_state": StringDatabaseField(name="sessions_uniq_state"),
        "total_session_duration_state": StringDatabaseField(name="total_session_duration_state"),
        "total_bounces_state": StringDatabaseField(name="total_bounces_state"),
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

    def create_hogql_context(self) -> HogQLContext:
        """Create and return a HogQL context with the web_overview_daily table added"""
        team_id = self.runner.team.pk

        # Create the database and HogQL context
        context = HogQLContext(
            team_id=team_id,
            enable_select_queries=True,
            database=create_hogql_database(team_id=team_id),
        )

        # Add the web_overview_daily table to the database
        context.database.web_overview_daily = WebOverviewDailyTable()

        return context

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

    def get_results(self) -> list[tuple[Any, ...]]:
        """Execute query against pre-aggregated tables using HogQL and return results

        This method is kept for backwards compatibility but should be deprecated in favor of get_query()
        """
        include_revenue = self.runner.query.includeRevenue
        team_id = self.runner.team.pk

        logger.info(
            "Executing pre-aggregated query directly",
            extra={
                "team_id": team_id,
            },
        )

        # Create HogQL context with the pre-aggregated table
        context = self.create_hogql_context()

        # Get the query
        select_query = self.get_query()

        try:
            # Execute the HogQL query
            result = execute_hogql_query(
                query_type="hogql_query", query=select_query, team=self.runner.team, context=context
            )

            logger.debug(
                "Successfully executed HogQL query", extra={"team_id": team_id, "result_count": len(result.results)}
            )

            # If there are no results, return an empty row to avoid errors
            if not result.results:
                return [(0, None, 0, None, 0, None, 0, None, 0, None, 0 if include_revenue else None, None)]

            return result.results

        except Exception as e:
            logger.exception("Error executing HogQL query", extra={"team_id": team_id, "error": str(e)})
            raise

    def _build_where_clause(self, team_id: int, date_from: str, date_to: str) -> ast.Expr:
        """Build the WHERE clause for the HogQL query"""
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
        # Map from PostHog property keys to pre-aggregated table field names
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
