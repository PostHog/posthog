import re
import datetime
from collections.abc import Callable
from typing import Any, Optional, TypeVar
from zoneinfo import ZoneInfo

from dateutil import parser
from dateutil.relativedelta import relativedelta
from rest_framework.exceptions import ValidationError

from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.property.property import ValueT
from posthog.models.team import Team
from posthog.queries.util import convert_to_datetime_aware
from posthog.utils import get_compare_period_dates

FilterType = TypeVar("FilterType", Filter, PathFilter)


def determine_compared_filter(filter: FilterType) -> FilterType:
    if not filter.date_to or not filter.date_from:
        raise ValidationError("You need date_from and date_to to compare")
    date_from, date_to = get_compare_period_dates(
        filter.date_from,
        filter.date_to,
        filter.date_from_delta_mapping,
        filter.date_to_delta_mapping,
        filter.interval,
    )

    return filter.shallow_clone({"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})


def convert_to_comparison(trend_entities: list[dict[str, Any]], filter, label: str) -> list[dict[str, Any]]:
    for entity in trend_entities:
        labels = [
            "{} {}".format(filter.interval if filter.interval is not None else "day", i)
            for i in range(len(entity["labels"]))
        ]
        entity.update(
            {
                "labels": labels,
                "days": entity["days"],
                "label": entity["label"],
                "compare_label": label,
                "compare": True,
            }
        )
    return trend_entities


"""
    handle_compare takes an Entity, Filter and a callable.
    It'll automatically create a new entity with the 'current' and 'previous' labels and automatically pick the right date_from and date_to filters .
    It will then call func(entity, filter, team_id).
"""


def handle_compare(filter, func: Callable, team: Team, **kwargs) -> list:
    all_entities = []
    base_entitites = func(filter=filter, team=team, **kwargs)
    if filter.compare:
        base_entitites = convert_to_comparison(base_entitites, filter, "current")
        all_entities.extend(base_entitites)

        compared_filter = determine_compared_filter(filter)
        comparison_entities = func(filter=compared_filter, team=team, **kwargs)
        comparison_entities = convert_to_comparison(comparison_entities, compared_filter, "previous")
        all_entities.extend(comparison_entities)
    else:
        all_entities.extend(base_entitites)
    return all_entities


def determine_parsed_incoming_date(
    value: ValueT | datetime.date | datetime.datetime | float,
) -> datetime.datetime | None:
    # This parses the incoming date value. The range of possibilities is only limited by our customers imagination, but usually
    # take the form of a string, a unix timestamp, or a datetime object.
    if isinstance(value, datetime.datetime):
        return convert_to_datetime_aware(value)

    if isinstance(value, datetime.date):
        return convert_to_datetime_aware(datetime.datetime.combine(value, datetime.time.min))

    if isinstance(value, int) or isinstance(value, float):
        return datetime.datetime.fromtimestamp(value, tz=ZoneInfo("UTC"))
    if isinstance(value, str):
        try:
            parsed = parser.parse(value)
            return convert_to_datetime_aware(parsed)
        except Exception:
            try:
                # This might be a Unix timestamp passed as a string in milliseconds
                parsed_date = float(value)
                return datetime.datetime.fromtimestamp(parsed_date, tz=ZoneInfo("UTC"))
            except Exception:
                try:
                    # This might be a Unix timestamp passed as a string in seconds
                    parsed_date = int(value)
                    return datetime.datetime.fromtimestamp(parsed_date, tz=ZoneInfo("UTC"))
                except Exception:
                    pass

    return None


def determine_parsed_date_for_property_matching(value: ValueT) -> datetime.datetime | None:
    # This parses the filter value we compare against. The range of possible values is limited by our UI.
    parsed_date = None
    try:
        parsed_date = relative_date_parse_for_feature_flag_matching(str(value))

        if not parsed_date:
            parsed_date = parser.parse(str(value))
            parsed_date = convert_to_datetime_aware(parsed_date)
    except Exception:
        return None

    return parsed_date


# Note: Any changes to this function need to be reflected in the rust version
# rust/feature-flags/src/properties/relative_date.rs
def relative_date_parse_for_feature_flag_matching(value: str) -> Optional[datetime.datetime]:
    regex = r"^-?(?P<number>[0-9]+)(?P<interval>[a-z])$"
    match = re.search(regex, value)
    parsed_dt = datetime.datetime.now(tz=ZoneInfo("UTC"))
    if match:
        number = int(match.group("number"))

        if number >= 10_000:
            # Guard against overflow, disallow numbers greater than 10_000
            return None

        interval = match.group("interval")
        if interval == "h":
            parsed_dt = parsed_dt - relativedelta(hours=number)
        elif interval == "d":
            parsed_dt = parsed_dt - relativedelta(days=number)
        elif interval == "w":
            parsed_dt = parsed_dt - relativedelta(weeks=number)
        elif interval == "m":
            parsed_dt = parsed_dt - relativedelta(months=number)
        elif interval == "y":
            parsed_dt = parsed_dt - relativedelta(years=number)
        else:
            return None

        return parsed_dt
    else:
        return None
