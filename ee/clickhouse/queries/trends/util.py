from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from ee.clickhouse.sql.events import EVENT_JOIN_PERSON_SQL
from posthog.models.entity import Entity
from posthog.models.filters import Filter

MATH_FUNCTIONS = {
    "sum": "sum",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "median": "quantile(0.50)",
    "p90": "quantile(0.90)",
    "p95": "quantile(0.95)",
    "p99": "quantile(0.99)",
}


def process_math(entity: Entity) -> Tuple[str, str, Dict[str, Optional[str]]]:
    aggregate_operation = "count(*)"
    params = {}
    join_condition = ""
    value = "toFloat64OrNull(JSONExtractRaw(properties, '{}'))".format(entity.math_property)
    if entity.math == "dau":
        join_condition = EVENT_JOIN_PERSON_SQL
        aggregate_operation = "count(DISTINCT person_id)"
    elif entity.math in MATH_FUNCTIONS:
        aggregate_operation = f"{MATH_FUNCTIONS[entity.math]}({value})"
        params = {"join_property_key": entity.math_property}

    return aggregate_operation, join_condition, params


def parse_response(stats: Dict, filter: Filter, additional_values: Dict = {}) -> Dict[str, Any]:
    counts = stats[1]
    dates = [
        item.strftime(
            "%Y-%m-%d{}".format(", %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    labels = [
        item.strftime(
            "%a. %-d %B{}".format(", %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    days = [
        item.strftime(
            "%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    return {
        "data": [float(c) for c in counts],
        "count": float(sum(counts)),
        "labels": labels,
        "days": days,
        **additional_values,
    }
