"""
Utility functions for insights processing, including filter conversion.
"""

import json
import structlog
from typing import Any, Optional

logger = structlog.get_logger(__name__)


def convert_filters_to_query(filters: str | dict) -> Optional[dict[str, Any]]:
    """
    Convert insight filters to modern query format or None if conversion fails.
    """
    try:
        filters_dict = _parse_filters(filters)
        if not filters_dict:
            return None

        # Get insight type and convert to query kind
        insight_type = filters_dict.get("insight", "TRENDS")
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

        query_dict = {"kind": query_kind}
        base_fields = {
            "interval": "interval",
            "properties": "properties",
            "filter_test_accounts": "filterTestAccounts",
        }
        _add_optional_fields(query_dict, filters_dict, base_fields)

        date_range: dict[str, Any] = {}
        for field in ["date_from", "date_to"]:
            if filters_dict.get(field):
                date_range[field] = filters_dict[field]
        if date_range:
            query_dict["dateRange"] = date_range  # type: ignore[assignment]

        # Insight-specific conversions
        if query_kind == "TrendsQuery":
            _convert_trends_filters(filters_dict, query_dict)
        elif query_kind == "FunnelsQuery":
            _convert_funnels_filters(filters_dict, query_dict)
        elif query_kind == "RetentionQuery":
            _convert_retention_filters(filters_dict, query_dict)

        return query_dict

    except Exception as e:
        logger.warning(f"Failed to convert filters to query: {e}")
        return None


def can_visualize_insight(insight: dict) -> bool:
    """
    Check if an insight can be visualized (has query or convertible filters).
    """
    # Has query - can visualize
    if insight.get("insight__query"):
        return True

    # Has filters that can be converted - can visualize
    insight_filters = insight.get("insight__filters")
    if insight_filters:
        converted = convert_filters_to_query(insight_filters)
        return converted is not None

    return False


def get_insight_type_from_filters(filters: str | dict) -> Optional[str]:
    """
    Extract insight type from filters.
    """
    filters_dict = _parse_filters(filters)
    return filters_dict.get("insight", "TRENDS") if filters_dict else None


def _parse_filters(filters: str | dict) -> Optional[dict[str, Any]]:
    """Parse filters from string or dict format."""
    try:
        if isinstance(filters, str):
            return json.loads(filters)
        elif isinstance(filters, dict):
            return filters
    except Exception:
        return None


def _add_optional_fields(target: dict, source: dict, field_mappings: dict[str, str]) -> None:
    """Add optional fields from source to target using field mappings."""
    for source_key, target_key in field_mappings.items():
        if source_key in source:
            target[target_key] = source[source_key]


def _create_series_item(item: dict, kind: str, math_support: bool = True) -> dict[str, Any]:
    """Create a series item for events or actions."""
    series_item = {"kind": kind}

    if kind == "EventsNode":
        event_id = item.get("id")
        if event_id is not None:
            series_item["event"] = str(event_id)
        if math_support:
            series_item["math"] = item.get("math", "total")
    else:  # ActionsNode
        action_id = item.get("id")
        if action_id is not None:
            series_item["id"] = str(action_id)
        if math_support:
            series_item["math"] = item.get("math", "total")

    optional_fields = {
        "name": "name",
        "custom_name": "custom_name",
        "math_property": "math_property",
        "properties": "properties",
    }
    _add_optional_fields(series_item, item, optional_fields)

    return series_item


def _convert_trends_filters(filters_dict: dict[str, Any], query_dict: dict[str, Any]) -> None:
    """Convert trends-specific filters to query format."""
    series = []
    for event in filters_dict.get("events", []):
        series.append(_create_series_item(event, "EventsNode", math_support=True))
    for action in filters_dict.get("actions", []):
        series.append(_create_series_item(action, "ActionsNode", math_support=True))

    if series:
        query_dict["series"] = series

    # Trends filter
    trends_filter: dict[str, Any] = {}
    trends_fields = {
        "display": "display",
        "formula": "formula",
        "show_legend": "showLegend",
        "show_values_on_series": "showValuesOnSeries",
    }
    _add_optional_fields(trends_filter, filters_dict, trends_fields)

    if trends_filter:
        query_dict["trendsFilter"] = trends_filter

    if filters_dict.get("compare"):
        query_dict["compareFilter"] = {"compare": filters_dict["compare"]}

    # Breakdown filter
    breakdown_filter: dict[str, Any] = {}
    breakdown_fields = {
        "breakdown": "breakdown",
        "breakdown_type": "breakdown_type",
        "breakdown_limit": "breakdown_limit",
    }
    _add_optional_fields(breakdown_filter, filters_dict, breakdown_fields)

    if breakdown_filter:
        query_dict["breakdownFilter"] = breakdown_filter


def _convert_funnels_filters(filters_dict: dict[str, Any], query_dict: dict[str, Any]) -> None:
    """Convert funnels-specific filters to query format."""
    series = []
    for event in filters_dict.get("events", []):
        series.append(_create_series_item(event, "EventsNode", math_support=False))
    for action in filters_dict.get("actions", []):
        series.append(_create_series_item(action, "ActionsNode", math_support=False))

    if series:
        query_dict["series"] = series

    # Funnels filter
    funnels_filter: dict[str, Any] = {}
    funnels_fields = {
        "funnel_window_interval": "funnelWindowInterval",
        "funnel_window_interval_unit": "funnelWindowIntervalUnit",
        "breakdown_attribution_type": "breakdownAttributionType",
    }
    _add_optional_fields(funnels_filter, filters_dict, funnels_fields)

    if funnels_filter:
        query_dict["funnelsFilter"] = funnels_filter


def get_basic_query_info(insight: dict[str, Any]) -> str | None:
    """Extract basic query information without execution."""
    try:
        insight_query: Any = insight.get("insight__query")
        insight_filters: Any = insight.get("insight__filters")

        query_dict: dict[str, Any] | None = None

        # Parse query or convert from filters
        if insight_query:
            if isinstance(insight_query, str):
                query_dict = json.loads(insight_query)
            elif isinstance(insight_query, dict):
                query_dict = insight_query
        elif insight_filters:
            query_dict = convert_filters_to_query(insight_filters)

        if not query_dict:
            return None

        info_parts: list[str] = []

        # Extract events/actions from series
        series: list[dict[str, Any]] = query_dict.get("series", [])
        if series:
            events: list[str] = [s.get("event") or s.get("name", "Unknown") for s in series[:3]]
            info_parts.append(f"Events: {', '.join(events)}")
            if len(series) > 3:
                info_parts[-1] += f" (+{len(series)-3} more)"

        # Extract date range
        date_range: dict[str, Any] = query_dict.get("dateRange", {})
        if date_range.get("date_from"):
            info_parts.append(f"Period: {date_range['date_from']}")

        return " | ".join(info_parts) if info_parts else "Basic query"

    except Exception:
        return "Query error"


def _convert_retention_filters(filters_dict: dict[str, Any], query_dict: dict[str, Any]) -> None:
    """Convert retention-specific filters to query format."""
    retention_filter: dict[str, Any] = {}
    retention_fields = {
        "retention_type": "retentionType",
        "returning_entity": "returningEntity",
        "target_entity": "targetEntity",
        "period": "period",
    }
    _add_optional_fields(retention_filter, filters_dict, retention_fields)

    if retention_filter:
        query_dict["retentionFilter"] = retention_filter
