"""Validation for dashboard-level filters on a cross-project dashboard.

A cross-project dashboard applies one filter set to tiles in several projects. Only filters
whose meaning survives that hop are allowed. A filter carrying an identifier means something
different in every project, so it is refused rather than dropped: a dropped filter produces a
plausible wrong number instead of an error.
"""

from typing import Any

from rest_framework import serializers

from posthog.hogql_queries.apply_dashboard_filters import (
    flatten_property_leaves,
    normalize_dashboard_filters_properties,
)

# Filter types that name a property, which resolves the same way in every project. Everything else
# is refused, including a filter with no type, because the schema reads a type-less leaf as a cohort.
NAME_BASED_PROPERTY_TYPES = frozenset({"event", "person", "element", "session", "event_metadata"})

# A breakdown with no type is an event breakdown, so None is allowed here.
NAME_BASED_BREAKDOWN_TYPES = frozenset({None, "event", "person", "session", "event_metadata"})

REFUSAL = (
    "This filter only works inside one project, so a cross-project dashboard cannot apply it. "
    "Use a date range, an interval, or a property filter that refers to a property by name."
)


def validate_cross_project_filters(filters: Any) -> dict[str, Any]:
    """Return the filters with grouped properties flattened, or raise ValidationError when a filter
    cannot cross a project boundary.

    The insight endpoint flattens AND property groups before it applies them, so a project-bound
    leaf inside a group is refused here the same as a top-level one.
    """
    if filters is None or filters == {}:
        return {}
    if not isinstance(filters, dict):
        raise serializers.ValidationError("Filters must be a dictionary.")

    try:
        normalized = normalize_dashboard_filters_properties(filters)
        leaves = flatten_property_leaves(normalized.get("properties"))
    except ValueError as error:
        raise serializers.ValidationError({"properties": str(error)}) from error

    for property_filter in leaves:
        property_type = property_filter.get("type")
        if property_type not in NAME_BASED_PROPERTY_TYPES:
            raise serializers.ValidationError({"properties": f"{property_type or 'untyped'}: {REFUSAL}"})

    breakdown = normalized.get("breakdown_filter")
    if isinstance(breakdown, dict):
        if breakdown.get("breakdown_type") not in NAME_BASED_BREAKDOWN_TYPES:
            raise serializers.ValidationError({"breakdown_filter": REFUSAL})
        if breakdown.get("breakdown_group_type_index") is not None:
            raise serializers.ValidationError({"breakdown_filter": REFUSAL})
        breakdowns = breakdown.get("breakdowns") or []
        if not isinstance(breakdowns, list):
            raise serializers.ValidationError({"breakdown_filter": "Breakdowns must be a list."})
        for item in breakdowns:
            if isinstance(item, dict) and (
                item.get("type") not in NAME_BASED_BREAKDOWN_TYPES or item.get("group_type_index") is not None
            ):
                raise serializers.ValidationError({"breakdown_filter": REFUSAL})

    return normalized
