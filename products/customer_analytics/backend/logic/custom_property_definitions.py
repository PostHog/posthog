"""Validation rules for custom account-property definitions, shared by the facade write paths."""

from typing import Any
from uuid import uuid4

from products.customer_analytics.backend.constants import CUSTOM_PROPERTY_OPTION_COLORS
from products.customer_analytics.backend.models import DATA_TYPE_BY_DISPLAY_TYPE, DataType, DisplayType


class InvalidCustomPropertyOptions(ValueError):
    """Raised when a select property's options fail validation; the viewset maps it to a 400."""


def coerce_is_big_number(display_type: str, is_big_number: bool) -> bool:
    """``is_big_number`` only applies to numeric display types; force it false otherwise.

    A one-way coercion (never rejects) that create and update apply so the flag can't be set on a
    non-numeric property.
    """
    return is_big_number and DATA_TYPE_BY_DISPLAY_TYPE[DisplayType(display_type)] == DataType.NUMERIC


def normalize_options(
    display_type: DisplayType,
    options: list[dict[str, Any]] | None,
    existing_ids: frozenset[str] = frozenset(),
) -> list[dict[str, Any]] | None:
    if display_type != DisplayType.SELECT:
        return None
    if not options:
        raise InvalidCustomPropertyOptions("A select property needs at least one option.")
    normalized = [_normalize_option(option, existing_ids) for option in options]
    _assert_unique_labels(normalized)
    return normalized


def _normalize_option(option: dict[str, Any], existing_ids: frozenset[str]) -> dict[str, Any]:
    label = (option.get("label") or "").strip()
    if not label:
        raise InvalidCustomPropertyOptions("Option labels can't be blank.")
    color = option.get("color")
    if color not in CUSTOM_PROPERTY_OPTION_COLORS:
        raise InvalidCustomPropertyOptions(f"Invalid option color: '{color}'.")
    option_id = option.get("id")
    if option_id and option_id not in existing_ids:
        raise InvalidCustomPropertyOptions("Option ids are assigned by the server; omit them for new options.")
    return {"id": option_id or str(uuid4()), "label": label, "color": color}


def _assert_unique_labels(options: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for option in options:
        if option["label"] in seen:
            raise InvalidCustomPropertyOptions(f"Duplicate option label: '{option['label']}'.")
        seen.add(option["label"])
