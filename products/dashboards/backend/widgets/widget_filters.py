"""Shared validation and query bridging for dashboard widget `config.widgetFilters`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from pydantic import ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import PropertyGroupFilter

from products.dashboards.backend.widget_specs.common import WidgetFilterEntry

WidgetFilterConfig = dict[str, WidgetFilterEntry]
WidgetFilterConfigInput = Mapping[str, WidgetFilterEntry | dict[str, object]]


def _coerce_widget_filter_entry(entry: WidgetFilterEntry | dict[str, object]) -> WidgetFilterEntry:
    if isinstance(entry, WidgetFilterEntry):
        return entry
    return WidgetFilterEntry.model_validate(entry)


def _parse_widget_filter_entry(filter_id: str, entry: object) -> WidgetFilterEntry:
    if not isinstance(filter_id, str) or not filter_id:
        raise DRFValidationError({"config": "widgetFilters keys must be non-empty strings."})
    if not isinstance(entry, dict):
        raise DRFValidationError({"config": "widgetFilters values must be objects."})

    entry_dict = dict(entry)
    entry_dict.setdefault("filterId", filter_id)
    try:
        parsed = WidgetFilterEntry.model_validate(entry_dict)
    except ValidationError as exc:
        message = "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors())
        raise DRFValidationError({"config": message or f"widgetFilters.{filter_id} is invalid."}) from exc

    if parsed.filterId != filter_id:
        raise DRFValidationError({"config": f"widgetFilters.{filter_id} filterId must match the key."})
    return parsed


def validate_widget_filters(config: dict[str, object]) -> WidgetFilterConfig | None:
    raw = config.get("widgetFilters")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DRFValidationError({"config": "widgetFilters must be an object."})

    raw_dict = cast(dict[str, object], raw)
    validated: WidgetFilterConfig = {
        filter_id: _parse_widget_filter_entry(filter_id, entry) for filter_id, entry in raw_dict.items()
    }
    return validated or None


def build_event_property_filters_from_widget_filters(
    widget_filters: WidgetFilterConfigInput | None,
) -> list[dict[str, Any]] | None:
    if not widget_filters:
        return None

    property_filters: list[dict[str, Any]] = []
    for entry in widget_filters.values():
        parsed_entry = _coerce_widget_filter_entry(entry)
        filter_value = parsed_entry.value
        property_filter: dict[str, Any] = {
            "type": "event",
            "key": parsed_entry.propertyName,
            "operator": parsed_entry.operator.value,
        }
        if filter_value is not None:
            property_filter["value"] = filter_value if isinstance(filter_value, list) else [filter_value]
        property_filters.append(property_filter)
    return property_filters


def build_property_group_filter_from_widget_filters(
    widget_filters: WidgetFilterConfigInput | None,
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
