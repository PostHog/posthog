"""Shared validation and query bridging for dashboard widget `config.widgetFilters`."""

from __future__ import annotations

from typing import Any, cast

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import PropertyGroupFilter, PropertyOperator

from products.dashboards.backend.widgets.widget_config_types import (
    WidgetFilterConfig,
    WidgetFilterConfigEntry,
    WidgetListConfigInputBase,
)

WIDGET_FILTER_OPERATORS = frozenset(operator.value for operator in PropertyOperator)

# Documented in widget_catalog config_schema_hints and OpenAPI widget config serializers.
WIDGET_FILTERS_CATALOG_HINT: dict[str, Any] = {
    "type": "object",
    "optional": True,
    "description": (
        "Widget filter selections keyed by filter id. Each key must match the entry's filterId. "
        "Configure filters in the product UI first, then copy filter id, option id, and property name here."
    ),
    "entry": {
        "filterId": {
            "type": "string",
            "required": True,
            "description": "Filter UUID; must equal the object key.",
        },
        "propertyName": {
            "type": "string",
            "required": True,
            "description": "Event property key applied by this filter (for example $environment).",
        },
        "optionId": {
            "type": "string",
            "required": True,
            "description": "Selected option id from the filter definition.",
        },
        "operator": {
            "type": "string",
            "required": True,
            "description": "Property filter operator (for example exact, is_not, icontains).",
        },
        "value": {
            "type": "string|array|null",
            "optional": True,
            "description": "Filter value as a string, list of strings, or null.",
        },
    },
}


def _parse_widget_filter_value(value: object) -> str | list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise DRFValidationError({"config": "widgetFilters value list items must be strings."})
        return cast(list[str], value)
    raise DRFValidationError({"config": "widgetFilters value must be a string, list, or null."})


def _parse_widget_filter_entry(filter_id: str, entry: object) -> WidgetFilterConfigEntry:
    if not isinstance(filter_id, str) or not filter_id:
        raise DRFValidationError({"config": "widgetFilters keys must be non-empty strings."})
    if not isinstance(entry, dict):
        raise DRFValidationError({"config": "widgetFilters values must be objects."})

    for required_key in ("filterId", "propertyName", "optionId", "operator"):
        if required_key not in entry:
            raise DRFValidationError({"config": f"widgetFilters.{filter_id} is missing {required_key}."})

    entry_filter_id = entry["filterId"]
    if not isinstance(entry_filter_id, str) or entry_filter_id != filter_id:
        raise DRFValidationError({"config": f"widgetFilters.{filter_id} filterId must match the key."})

    property_name = entry["propertyName"]
    if not isinstance(property_name, str) or not property_name:
        raise DRFValidationError({"config": f"widgetFilters.{filter_id} propertyName must be a non-empty string."})

    option_id = entry["optionId"]
    if not isinstance(option_id, str) or not option_id:
        raise DRFValidationError({"config": f"widgetFilters.{filter_id} optionId must be a non-empty string."})

    operator = entry["operator"]
    if not isinstance(operator, str) or not operator:
        raise DRFValidationError({"config": f"widgetFilters.{filter_id} operator must be a non-empty string."})
    if operator not in WIDGET_FILTER_OPERATORS:
        raise DRFValidationError({"config": f"widgetFilters.{filter_id} operator {operator!r} is not supported."})

    parsed: WidgetFilterConfigEntry = {
        "filterId": filter_id,
        "propertyName": property_name,
        "optionId": option_id,
        "operator": operator,
    }
    if "value" in entry:
        parsed["value"] = _parse_widget_filter_value(entry["value"])
    return parsed


def validate_widget_filters(config: WidgetListConfigInputBase) -> WidgetFilterConfig | None:
    raw = config.get("widgetFilters")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DRFValidationError({"config": "widgetFilters must be an object."})

    validated: WidgetFilterConfig = {
        filter_id: _parse_widget_filter_entry(filter_id, entry) for filter_id, entry in raw.items()
    }
    return validated or None


def build_event_property_filters_from_widget_filters(
    widget_filters: WidgetFilterConfig | None,
) -> list[dict[str, Any]] | None:
    if not widget_filters:
        return None

    property_filters: list[dict[str, Any]] = []
    for entry in widget_filters.values():
        filter_value = entry.get("value")
        property_filter: dict[str, Any] = {
            "type": "event",
            "key": entry["propertyName"],
            "operator": entry["operator"],
        }
        if filter_value is not None:
            property_filter["value"] = filter_value if isinstance(filter_value, list) else [filter_value]
        property_filters.append(property_filter)
    return property_filters


def build_property_group_filter_from_widget_filters(
    widget_filters: WidgetFilterConfig | None,
) -> PropertyGroupFilter | None:
    property_filters = build_event_property_filters_from_widget_filters(widget_filters)
    if not property_filters:
        return None

    return PropertyGroupFilter.model_validate(
        {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": property_filters,
                }
            ],
        }
    )
