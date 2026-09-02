from datetime import UTC, datetime
from typing import Any, Optional, Union, overload
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError

from posthog.interval_specs import UnsupportedIntervalError, get_trunc_func
from posthog.models.team.team import Team, WeekStartDay
from posthog.schema_enums import PersonsOnEventsMode


@overload
def alias_poe_mode_for_legacy(persons_on_events_mode: PersonsOnEventsMode) -> PersonsOnEventsMode: ...
@overload
def alias_poe_mode_for_legacy(persons_on_events_mode: PersonsOnEventsMode | None) -> PersonsOnEventsMode | None: ...
def alias_poe_mode_for_legacy(persons_on_events_mode: PersonsOnEventsMode | None) -> PersonsOnEventsMode | None:
    if persons_on_events_mode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED:
        # PERSON_ID_OVERRIDE_PROPERTIES_JOINED is not implemented in legacy insights
        # It's functionally the same as DISABLED, just slower - hence aliasing to DISABLED
        return PersonsOnEventsMode.DISABLED
    return persons_on_events_mode


TIME_IN_SECONDS: dict[str, Any] = {
    "hour": 3600,
    "day": 3600 * 24,
    "week": 3600 * 24 * 7,
    "month": 3600 * 24 * 30,  # TODO: Let's get rid of this lie! Months are not all 30 days long
}


# TODO: refactor since this is only used in one spot now
def format_ch_timestamp(timestamp: datetime, convert_to_timezone: Optional[str] = None):
    if convert_to_timezone:
        # Here we probably get a timestamp set to the beginning of the day (00:00), in UTC
        # We need to convert that UTC timestamp to the local timestamp (00:00 in US/Pacific for example)
        # Then we convert it back to UTC (08:00 in UTC)
        if timestamp.tzinfo and timestamp.tzinfo != ZoneInfo("UTC"):
            raise ValidationError(detail="You must pass a timestamp with no timezone or UTC")
        timestamp = timestamp.replace(tzinfo=ZoneInfo(convert_to_timezone)).astimezone(ZoneInfo("UTC"))
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def get_start_of_interval_sql(
    interval: str,
    *,
    team: Team,
    source: str = "timestamp",
    ensure_datetime: bool = False,
) -> str:
    trunc_func = get_trunc_func_ch(interval)
    if source.startswith("%(") and source.endswith(")s"):
        source = f"toDateTime({source}, %(timezone)s)"
    elif "%(timezone)s" not in source:
        source = f"toTimeZone(toDateTime({source}, 'UTC'), %(timezone)s)"
    trunc_func_args = [source]
    if trunc_func == "toStartOfWeek":
        trunc_func_args.append((WeekStartDay(team.week_start_day or 0)).clickhouse_mode)
    interval_sql = f"{trunc_func}({', '.join(trunc_func_args)})"
    # For larger intervals dates are returned instead of datetimes, and we always want datetimes for comparisons
    return f"toDateTime({interval_sql}, %(timezone)s)" if ensure_datetime else interval_sql


def get_trunc_func_ch(period: Optional[str]) -> str:
    try:
        return get_trunc_func(period)
    except UnsupportedIntervalError:
        raise ValidationError(f"Period {period} is unsupported.")


def convert_to_datetime_aware(date_obj):
    if date_obj.tzinfo is None:
        date_obj = date_obj.replace(tzinfo=UTC)
    return date_obj


def correct_result_for_sampling(
    value: Union[int, float],
    sampling_factor: Optional[float],
    entity_math: Optional[str] = None,
) -> Union[int, float]:
    from posthog.queries.trends.util import ALL_SUPPORTED_MATH_FUNCTIONS

    # We don't adjust results for sampling if:
    # - There's no sampling_factor specified i.e. the query isn't sampled
    # - The value is not a number (should not happen, but being defensive, especially against HogQL aggregation)
    # - The query performs a math operation other than 'sum' because statistical math operations
    # on sampled data yield results in the correct format
    if (
        not sampling_factor
        or not isinstance(value, int | float)
        or (entity_math is not None and entity_math != "sum" and entity_math in ALL_SUPPORTED_MATH_FUNCTIONS)
    ):
        return value

    result = round(value * (1 / sampling_factor))
    return result
