from typing import Any


REVENUECAT_EVENT_DOUBLE_FIELDS = frozenset({"price", "price_in_purchased_currency"})


def normalize_revenuecat_event_types(row: dict[str, Any]) -> dict[str, Any]:
    for field in REVENUECAT_EVENT_DOUBLE_FIELDS:
        value = row.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            row[field] = float(value)
    return row
