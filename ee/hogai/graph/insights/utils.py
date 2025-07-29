"""
Utility functions for insights processing, including legacy filter conversion.
"""

import json
import structlog
from typing import Any, Optional

logger = structlog.get_logger(__name__)


def convert_legacy_filters_to_query(filters: str | dict) -> Optional[dict[str, Any]]:
    """
    Convert legacy insight filters to modern query format.

    Args:
        filters: Legacy filter dictionary or JSON string

    Returns:
        Modern query dictionary or None if conversion fails
    """
    try:
        # Parse filters if it's a string
        if isinstance(filters, str):
            filters_dict = json.loads(filters)
        elif isinstance(filters, dict):
            filters_dict = filters
        else:
            return None

        # Get insight type - default to trends if not specified
        insight_type = filters_dict.get("insight", "TRENDS")

        # Map insight types to query kinds
        insight_type_to_query_kind = {
            "TRENDS": "TrendsQuery",
            "FUNNELS": "FunnelsQuery",
            "RETENTION": "RetentionQuery",
            "PATHS": "PathsQuery",
            "STICKINESS": "StickinessQuery",
            "LIFECYCLE": "LifecycleQuery",
        }

        query_kind = insight_type_to_query_kind.get(insight_type)
        if not query_kind:
            return None

        # Build base query structure
        query_dict = {
            "kind": query_kind,
        }

        # Add date range
        date_range = {}
        if filters_dict.get("date_from"):
            date_range["date_from"] = filters_dict["date_from"]
        if filters_dict.get("date_to"):
            date_range["date_to"] = filters_dict["date_to"]
        if date_range:
            query_dict["dateRange"] = date_range

        # Add interval
        if filters_dict.get("interval"):
            query_dict["interval"] = filters_dict["interval"]

        # Add global properties
        if filters_dict.get("properties"):
            query_dict["properties"] = filters_dict["properties"]

        # Add filter test accounts
        if "filter_test_accounts" in filters_dict:
            query_dict["filterTestAccounts"] = filters_dict["filter_test_accounts"]

        # Handle insight-specific conversions
        if query_kind == "TrendsQuery":
            _convert_trends_filters(filters_dict, query_dict)
        elif query_kind == "FunnelsQuery":
            _convert_funnels_filters(filters_dict, query_dict)
        elif query_kind == "RetentionQuery":
            _convert_retention_filters(filters_dict, query_dict)

        return query_dict

    except Exception as e:
        logger.warning(f"Failed to convert legacy filters to query: {e}")
        return None


def _convert_trends_filters(filters_dict: dict[str, Any], query_dict: dict[str, Any]) -> None:
    """Convert trends-specific filters to query format."""
    series = []

    # Handle events
    events = filters_dict.get("events", [])
    for event in events:
        series_item = {
            "kind": "EventsNode",
            "event": event.get("id"),
            "math": event.get("math", "total"),
        }

        # Add custom name if present
        if event.get("name"):
            series_item["name"] = event["name"]
        if event.get("custom_name"):
            series_item["custom_name"] = event["custom_name"]

        # Add math property if present
        if event.get("math_property"):
            series_item["math_property"] = event["math_property"]

        # Add properties if present
        if event.get("properties"):
            series_item["properties"] = event["properties"]

        series.append(series_item)

    # Handle actions
    actions = filters_dict.get("actions", [])
    for action in actions:
        series_item = {
            "kind": "ActionsNode",
            "id": action.get("id"),
            "math": action.get("math", "total"),
        }

        # Add name if present
        if action.get("name"):
            series_item["name"] = action["name"]
        if action.get("custom_name"):
            series_item["custom_name"] = action["custom_name"]

        # Add math property if present
        if action.get("math_property"):
            series_item["math_property"] = action["math_property"]

        # Add properties if present
        if action.get("properties"):
            series_item["properties"] = action["properties"]

        series.append(series_item)

    if series:
        query_dict["series"] = series

    # Add trends filter
    trends_filter = {}

    # Display type
    if filters_dict.get("display"):
        trends_filter["display"] = filters_dict["display"]

    # Formula
    if filters_dict.get("formula"):
        trends_filter["formula"] = filters_dict["formula"]

    # Show legend
    if "show_legend" in filters_dict:
        trends_filter["showLegend"] = filters_dict["show_legend"]

    # Show values on series
    if "show_values_on_series" in filters_dict:
        trends_filter["showValuesOnSeries"] = filters_dict["show_values_on_series"]

    # Compare to previous period
    if filters_dict.get("compare"):
        trends_filter["compare"] = filters_dict["compare"]

    if trends_filter:
        query_dict["trendsFilter"] = trends_filter

    # Add breakdown filter
    breakdown_filter = {}
    if filters_dict.get("breakdown"):
        breakdown_filter["breakdown"] = filters_dict["breakdown"]
    if filters_dict.get("breakdown_type"):
        breakdown_filter["breakdown_type"] = filters_dict["breakdown_type"]
    if filters_dict.get("breakdown_limit"):
        breakdown_filter["breakdown_limit"] = filters_dict["breakdown_limit"]
    if breakdown_filter:
        query_dict["breakdownFilter"] = breakdown_filter


def _convert_funnels_filters(filters_dict: dict[str, Any], query_dict: dict[str, Any]) -> None:
    """Convert funnels-specific filters to query format."""
    series = []

    # Handle events
    events = filters_dict.get("events", [])
    for event in events:
        series_item = {
            "kind": "EventsNode",
            "event": event.get("id"),
        }

        # Add properties if present
        if event.get("properties"):
            series_item["properties"] = event["properties"]

        series.append(series_item)

    # Handle actions
    actions = filters_dict.get("actions", [])
    for action in actions:
        series_item = {
            "kind": "ActionsNode",
            "id": action.get("id"),
        }

        # Add properties if present
        if action.get("properties"):
            series_item["properties"] = action["properties"]

        series.append(series_item)

    if series:
        query_dict["series"] = series

    # Add funnels filter
    funnels_filter = {}

    if filters_dict.get("funnel_window_interval"):
        funnels_filter["funnelWindowInterval"] = filters_dict["funnel_window_interval"]

    if filters_dict.get("funnel_window_interval_unit"):
        funnels_filter["funnelWindowIntervalUnit"] = filters_dict["funnel_window_interval_unit"]

    if filters_dict.get("breakdown_attribution_type"):
        funnels_filter["breakdownAttributionType"] = filters_dict["breakdown_attribution_type"]

    if funnels_filter:
        query_dict["funnelsFilter"] = funnels_filter


def _convert_retention_filters(filters_dict: dict[str, Any], query_dict: dict[str, Any]) -> None:
    """Convert retention-specific filters to query format."""
    retention_filter = {}

    if filters_dict.get("retention_type"):
        retention_filter["retentionType"] = filters_dict["retention_type"]

    if filters_dict.get("returning_entity"):
        retention_filter["returningEntity"] = filters_dict["returning_entity"]

    if filters_dict.get("target_entity"):
        retention_filter["targetEntity"] = filters_dict["target_entity"]

    if filters_dict.get("period"):
        retention_filter["period"] = filters_dict["period"]

    if retention_filter:
        query_dict["retentionFilter"] = retention_filter


def can_visualize_insight(insight: dict) -> bool:
    """
    Check if an insight can be visualized (has query or convertible filters).

    Args:
        insight: Insight dictionary from database

    Returns:
        True if insight can be visualized, False otherwise
    """
    # Has query - can visualize
    if insight.get("insight__query"):
        return True

    # Has filters that can be converted - can visualize
    insight_filters = insight.get("insight__filters")
    if insight_filters:
        converted = convert_legacy_filters_to_query(insight_filters)
        return converted is not None

    return False


def get_insight_type_from_filters(filters: str | dict) -> Optional[str]:
    """
    Extract insight type from legacy filters.

    Args:
        filters: Legacy filter dictionary or JSON string

    Returns:
        Insight type string or None if not found
    """
    try:
        if isinstance(filters, str):
            filters_dict = json.loads(filters)
        elif isinstance(filters, dict):
            filters_dict = filters
        else:
            return None

        return filters_dict.get("insight", "TRENDS")
    except Exception:
        return None
