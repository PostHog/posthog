"""Validation rules for custom account-property definitions, shared by the facade write paths."""

from typing import Any
from uuid import uuid4

from django.db.models import Case, F, QuerySet, TextField, Value, When

from products.customer_analytics.backend.constants import CUSTOM_PROPERTY_OPTION_COLORS
from products.customer_analytics.backend.models import (
    DATA_TYPE_BY_DISPLAY_TYPE,
    CustomPropertyValue,
    DataType,
    DisplayType,
)


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


def apply_option_side_effects(
    *,
    team_id: int,
    definition_id: Any,
    previous_options: list[dict[str, Any]] | None,
    new_options: list[dict[str, Any]] | None,
) -> None:
    previous_by_id = {option["id"]: option for option in previous_options or []}
    new_by_id = {option["id"]: option for option in new_options or []}
    removed_labels = [option["label"] for option_id, option in previous_by_id.items() if option_id not in new_by_id]
    renames = [
        (previous_by_id[option_id]["label"], option["label"])
        for option_id, option in new_by_id.items()
        if option_id in previous_by_id and previous_by_id[option_id]["label"] != option["label"]
    ]
    values = CustomPropertyValue.objects.for_team(team_id).filter(definition_id=definition_id)
    _soft_delete_active_values(values, labels=removed_labels)
    _backfill_renamed_labels(values, renames=renames)


def _soft_delete_active_values(values: QuerySet[CustomPropertyValue], *, labels: list[str]) -> None:
    if labels:
        values.filter(value_str__in=labels, is_deleted=False).update(is_deleted=True)


# Compromise: rewrites value rows inline, within the definition-update transaction — see COMPROMISES.md.
def _backfill_renamed_labels(values: QuerySet[CustomPropertyValue], *, renames: list[tuple[str, str]]) -> None:
    if not renames:
        return
    values.filter(value_str__in=[old_label for old_label, _ in renames]).update(
        value_str=Case(
            *[When(value_str=old_label, then=Value(new_label)) for old_label, new_label in renames],
            default=F("value_str"),
            output_field=TextField(),
        )
    )
