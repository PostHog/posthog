from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from ee.clickhouse.sql.events import EVENT_JOIN_PERSON_SQL
from posthog.models.entity import Entity
from posthog.models.filters import Filter


def process_math(entity: Entity) -> Tuple[str, str, Dict[str, Optional[str]]]:
    aggregate_operation = "count(*)"
    params = {}
    join_condition = ""
    value = "toFloat64OrNull(JSONExtractRaw(properties, '{}'))".format(entity.math_property)
    if entity.math == "dau":
        join_condition = EVENT_JOIN_PERSON_SQL
        aggregate_operation = "count(DISTINCT person_id)"
    elif entity.math == "sum":
        aggregate_operation = "sum({})".format(value)
        params = {"join_property_key": entity.math_property}
    elif entity.math == "avg":
        aggregate_operation = "avg({})".format(value)
        params = {"join_property_key": entity.math_property}
    elif entity.math == "min":
        aggregate_operation = "min({})".format(value)
        params = {"join_property_key": entity.math_property}
    elif entity.math == "max":
        aggregate_operation = "max({})".format(value)
        params = {"join_property_key": entity.math_property}

    return aggregate_operation, join_condition, params


def parse_response(stats: Dict, filter: Filter, additional_values: Dict = {}) -> Dict[str, Any]:
    counts = stats[1]
    dates = [
        ((item - timedelta(days=1)) if filter.interval == "month" else item).strftime(
            "%Y-%m-%d{}".format(", %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    labels = [
        ((item - timedelta(days=1)) if filter.interval == "month" else item).strftime(
            "%a. %-d %B{}".format(", %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    days = [
        ((item - timedelta(days=1)) if filter.interval == "month" else item).strftime(
            "%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    return {
        "data": counts,
        "count": sum(counts),
        "dates": dates,
        "labels": labels,
        "days": days,
        **additional_values,
    }
