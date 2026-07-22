from collections.abc import Iterable
from typing import Any

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.leaf_shape import walk_filter_leaves

_INTERVAL_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def derive_window_days(time_value: object, time_interval: object) -> int:
    if not isinstance(time_interval, str):
        return 0
    if not isinstance(time_value, (int, float, str)):
        return 0
    try:
        normalized_time_value = max(0, int(time_value))
    except (TypeError, ValueError):
        return 0
    return normalized_time_value * _INTERVAL_DAYS.get(time_interval, 0)


def pin_conditions_for_cohorts(cohorts: Iterable[Cohort]) -> tuple[dict[str, Any], list[str]]:
    conditions: list[dict[str, Any]] = []
    event_names: set[str] = set()

    for cohort in sorted(cohorts, key=lambda item: item.id):
        properties = (cohort.filters or {}).get("properties")
        for leaf in walk_filter_leaves(properties):
            if leaf.get("type") != "behavioral" or leaf.get("conditionHash") is None:
                continue

            event_key = leaf.get("key")
            is_action = leaf.get("event_type") == "actions" or isinstance(event_key, int)
            event_name = event_key if isinstance(event_key, str) and not is_action else None
            if event_name is not None:
                event_names.add(event_name)

            conditions.append(
                {
                    "cohort_id": cohort.id,
                    "condition_hash": leaf.get("conditionHash"),
                    "value": leaf.get("value"),
                    "time_value": leaf.get("time_value"),
                    "time_interval": leaf.get("time_interval"),
                    "explicit_datetime": leaf.get("explicit_datetime"),
                    "explicit_datetime_to": leaf.get("explicit_datetime_to"),
                    "operator": leaf.get("operator"),
                    "operator_value": leaf.get("operator_value"),
                    "window_days": derive_window_days(leaf.get("time_value"), leaf.get("time_interval")),
                    "event_name": event_name,
                    "is_action": is_action,
                }
            )

    conditions.sort(key=lambda item: (item["cohort_id"], item["condition_hash"], item["event_name"] or ""))
    return {"schema_version": 1, "conditions": conditions}, sorted(event_names)
