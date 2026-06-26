"""Validation rules for custom account-property definitions, shared by the facade write paths."""

from products.customer_analytics.backend.models import DATA_TYPE_BY_DISPLAY_TYPE, DataType, DisplayType


def coerce_is_big_number(display_type: str, is_big_number: bool) -> bool:
    """``is_big_number`` only applies to numeric display types; force it false otherwise.

    A one-way coercion (never rejects) that create and update apply so the flag can't be set on a
    non-numeric property.
    """
    return is_big_number and DATA_TYPE_BY_DISPLAY_TYPE[DisplayType(display_type)] == DataType.NUMERIC
