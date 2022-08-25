import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import pytz
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.constants import TRENDS_CUMULATIVE, WEEKLY_ACTIVE
from posthog.models.entity import Entity
from posthog.models.event.sql import EVENT_JOIN_PERSON_SQL
from posthog.models.filters import Filter, PathFilter
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.property.util import get_property_string_expr
from posthog.models.team import Team
from posthog.queries.util import format_ch_timestamp, get_earliest_timestamp
from posthog.utils import encode_get_request_params

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


def process_math(
    entity: Entity, team: Team, event_table_alias: Optional[str] = None, person_id_alias: str = "person_id"
) -> Tuple[str, str, Dict[str, Any]]:
    aggregate_operation = "count(*)"
    join_condition = ""
    params: Dict[str, Any] = {}
    if entity.math == "dau":
        if team.aggregate_users_by_distinct_id:
            join_condition = ""
            aggregate_operation = f"count(DISTINCT {event_table_alias + '.' if event_table_alias else ''}distinct_id)"
        else:
            join_condition = EVENT_JOIN_PERSON_SQL
            aggregate_operation = f"count(DISTINCT {person_id_alias})"
    elif entity.math == "unique_group":
        validate_group_type_index("math_group_type_index", entity.math_group_type_index, required=True)

        aggregate_operation = f"count(DISTINCT $group_{entity.math_group_type_index})"
    elif entity.math == "unique_session":
        aggregate_operation = f"count(DISTINCT {event_table_alias + '.' if event_table_alias else ''}$session_id)"
    elif entity.math in MATH_FUNCTIONS:
        if entity.math_property is None:
            raise ValidationError({"math_property": "This field is required when `math` is set."}, code="required")

        if entity.math_property == "$session_duration":
            aggregate_operation = f"{MATH_FUNCTIONS[entity.math]}(session_duration)"
        else:
            key = f"e_{entity.index}_math_prop"
            value, _ = get_property_string_expr("events", entity.math_property, f"%({key})s", "properties")
            aggregate_operation = f"{MATH_FUNCTIONS[entity.math]}(toFloat64OrNull({value}))"
            params[key] = entity.math_property

    return aggregate_operation, join_condition, params


def parse_response(stats: Dict, filter: Filter, additional_values: Dict = {}) -> Dict[str, Any]:
    counts = stats[1]
    labels = [item.strftime("%-d-%b-%Y{}".format(" %H:%M" if filter.interval == "hour" else "")) for item in stats[0]]
    days = [item.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" else "")) for item in stats[0]]
    return {
        "data": [float(c) for c in counts],
        "count": float(sum(counts)),
        "labels": labels,
        "days": days,
        **additional_values,
    }


def get_active_user_params(filter: Union[Filter, PathFilter], entity: Entity, team_id: int) -> Dict[str, Any]:
    params = {}
    params.update({"prev_interval": "7 DAY" if entity.math == WEEKLY_ACTIVE else "30 day"})
    diff = timedelta(days=7) if entity.math == WEEKLY_ACTIVE else timedelta(days=30)
    if filter.date_from:
        params.update(
            {"parsed_date_from_prev_range": f"AND timestamp >= '{format_ch_timestamp(filter.date_from - diff)}'"}
        )
    else:
        try:
            earliest_date = get_earliest_timestamp(team_id)
        except IndexError:
            raise ValidationError("Active User queries require a lower date bound")
        else:
            params.update(
                {"parsed_date_from_prev_range": f"AND timestamp >= '{format_ch_timestamp(earliest_date - diff)}'"}
            )

    return params


def enumerate_time_range(filter: Filter, seconds_in_interval: int) -> List[str]:
    date_from = filter.date_from
    date_to = filter.date_to
    delta = timedelta(seconds=seconds_in_interval)
    time_range: List[str] = []

    if not date_from or not date_to:
        return time_range

    while date_from <= date_to:
        time_range.append(date_from.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" else "")))
        date_from += delta
    return time_range


def get_next_interval_date_to(date_from: datetime, filter: Filter) -> Filter:
    date_from = date_from or timezone.now()
    if filter.interval == "month":
        return date_from + relativedelta(months=1)
    elif filter.interval == "week":
        return date_from + relativedelta(weeks=1)
    elif filter.interval == "day":
        return (date_from) + relativedelta(days=1)
    elif filter.interval == "hour":
        return date_from + relativedelta(hours=1)
    return None


def build_persons_urls(
    filter: Filter, entity: Entity, team_id: int, dates: List[datetime], additional_params: Dict[str, Any] = {},
) -> List[Dict[str, Any]]:
    persons_urls = []
    for date in dates:
        date_in_utc = datetime(
            date.year,
            date.month,
            date.day,
            getattr(date, "hour", 0),
            getattr(date, "minute", 0),
            getattr(date, "second", 0),
            tzinfo=getattr(date, "tzinfo", pytz.UTC),
        ).astimezone(pytz.UTC)
        filter_params = filter.to_params()
        interval_date_to = get_next_interval_date_to(date_in_utc, filter)

        extra_params = {
            "entity_id": entity.id,
            "entity_type": entity.type,
            "entity_math": entity.math,
            "date_from": filter.date_from if filter.display == TRENDS_CUMULATIVE else date_in_utc,
            "date_to": interval_date_to,
            "entity_order": entity.order,
        }

        if additional_params:
            extra_params.update(additional_params)

        parsed_params: Dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
        persons_urls.append(
            {
                "filter": extra_params,
                "url": f"api/projects/{team_id}/actions/people/?{urllib.parse.urlencode(parsed_params)}",
            }
        )
    return persons_urls
