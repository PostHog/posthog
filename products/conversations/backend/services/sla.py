"""SLA deadline calculation honoring optional working-hours windows.

The calculator walks wall-clock minutes inside the configured window. Using
wall-clock (not UTC-elapsed) arithmetic means "9-5" is always 8 business hours
regardless of DST transitions inside the day, which is what users expect when
they describe an SLA in terms of working hours.
"""

from datetime import (
    UTC,
    datetime,
    time as dtime,
    timedelta,
)
from typing import Any, Literal, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class BusinessHoursConfig(TypedDict, total=False):
    """Shape of the `sla_business_hours` JSON blob.

    All keys are optional. A blank config is treated as calendar hours.
    """

    days: list[str]  # lowercase weekday names, e.g. ['monday', 'tuesday']
    time: Literal["any"] | list[str] | tuple[str, str]  # 'any' or ['HH:MM', 'HH:MM']
    timezone: str  # IANA zone name, defaults to 'UTC' when omitted


WEEKDAYS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_WEEKDAY_SET = frozenset(WEEKDAYS)

_VALID_UNITS = ("minute", "hour", "day")

# Safety cap: 5 years of iterations, should never hit this with a valid config
_MAX_DAY_ITERATIONS = 365 * 5


def is_calendar_hours(business_hours: BusinessHoursConfig | dict[str, Any] | None) -> bool:
    """Return True when the config is equivalent to plain calendar hours.

    No config, or all-7-weekdays + any-time, collapses to `now + timedelta`.
    Strict equality against the canonical weekday set — 7 arbitrary strings
    don't count.
    """
    if not business_hours:
        return True
    days = business_hours.get("days") or []
    time_cfg = business_hours.get("time", "any")
    try:
        day_set = set(days) if not isinstance(days, str) else set()
    except TypeError:
        return False
    return day_set == _WEEKDAY_SET and time_cfg == "any"


def _parse_hhmm(value: Any, field: str) -> dtime:
    """Parse a 'HH:MM' string into a time object, rejecting garbage early."""
    if not isinstance(value, str):
        raise ValueError(f"business_hours.time[{field}] must be a 'HH:MM' string")
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"business_hours.time[{field}] must be 'HH:MM', got {value!r}")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as err:
        raise ValueError(f"business_hours.time[{field}] must be 'HH:MM', got {value!r}") from err
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        raise ValueError(f"business_hours.time[{field}] out of range, got {value!r}")
    return dtime(hour, minute)


def _parse_window(business_hours: BusinessHoursConfig | dict[str, Any]) -> tuple[dtime, dtime, int, bool]:
    """Return (start, end, window_minutes, is_any_time).

    For time == "any" we treat the window as the full 24h. For a custom range
    we require start < end (no overnight windows).
    """
    time_cfg = business_hours.get("time", "any")
    if time_cfg == "any":
        return dtime(0, 0), dtime(0, 0), 24 * 60, True

    if not (isinstance(time_cfg, list | tuple) and len(time_cfg) == 2):
        raise ValueError("business_hours.time must be 'any' or [start, end]")

    start_time = _parse_hhmm(time_cfg[0], "start")
    end_time = _parse_hhmm(time_cfg[1], "end")
    start_min = start_time.hour * 60 + start_time.minute
    end_min = end_time.hour * 60 + end_time.minute
    if end_min <= start_min:
        raise ValueError("business_hours.time end must be strictly after start")
    return start_time, end_time, end_min - start_min, False


def _to_minutes(amount: float, unit: str, window_minutes: int) -> float:
    """Convert a user amount into wall-clock minutes inside the window.

    `day` with a custom window means one window-length (9-17 => 1 day == 8h).
    `day` with `time: 'any'` means 24 wall-clock hours.
    """
    if unit == "minute":
        return amount
    if unit == "hour":
        return amount * 60
    if unit == "day":
        return amount * window_minutes
    raise ValueError(f"Unknown SLA unit: {unit}")


def _validate_days(raw: Any) -> set[str]:
    if isinstance(raw, str):
        raise ValueError("business_hours.days must be a list of weekday names, not a string")
    try:
        day_set = set(raw or [])
    except TypeError as err:
        raise ValueError("business_hours.days must be iterable") from err
    if not day_set:
        raise ValueError("business_hours.days must be non-empty")
    unknown = day_set - _WEEKDAY_SET
    if unknown:
        raise ValueError(f"Unknown weekday names: {sorted(unknown)}")
    return day_set


def _resolve_timezone(raw: Any) -> ZoneInfo:
    tz_name = raw or "UTC"
    if not isinstance(tz_name, str):
        raise ValueError("business_hours.timezone must be an IANA zone string")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as err:
        raise ValueError(f"Invalid timezone: {tz_name}") from err


def compute_sla_deadline(
    now: datetime,
    amount: float,
    unit: str,
    business_hours: BusinessHoursConfig | dict[str, Any] | None,
) -> datetime:
    """Compute the SLA deadline as an aware UTC datetime.

    Args:
        now: Aware datetime. Converted to the window's timezone for walking
            and back to UTC for the return value.
        amount: Strictly positive quantity of `unit`.
        unit: One of 'minute', 'hour', 'day'.
        business_hours: Optional dict with keys:
            - days: list of lowercase weekday names (Monday = first)
            - time: 'any' or [HH:MM, HH:MM] with start strictly < end
            - timezone: IANA zone name (e.g. 'America/New_York'), defaults UTC

        If `business_hours` is None, or covers all 7 days at any time, the
        calculation collapses to `now + timedelta(...)` (calendar hours).
        In that fast path the configured `timezone` is ignored — "always
        business" is timezone-independent, so `now + 2 days` is 48h of UTC
        elapsed (which is only 47h wall-clock across spring-forward DST).
        To get wall-clock-stable semantics across DST, constrain either
        `days` or `time` to something other than all/any.

    Returns:
        Aware datetime in UTC.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if unit not in _VALID_UNITS:
        raise ValueError(f"Unknown SLA unit: {unit}")
    if amount <= 0:
        raise ValueError("amount must be > 0")

    if is_calendar_hours(business_hours):
        if unit == "minute":
            delta = timedelta(minutes=amount)
        elif unit == "hour":
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        return (now + delta).astimezone(UTC)

    assert business_hours is not None
    day_set = _validate_days(business_hours.get("days"))
    tz = _resolve_timezone(business_hours.get("timezone"))
    start_time, end_time, window_minutes, is_any_time = _parse_window(business_hours)
    remaining = _to_minutes(amount, unit, window_minutes)

    # Walk in wall-clock (naive) so 9-5 is always 8h regardless of DST.
    cursor_wall = now.astimezone(tz).replace(tzinfo=None)

    for _ in range(_MAX_DAY_ITERATIONS):
        day_name = WEEKDAYS[cursor_wall.weekday()]
        if day_name in day_set:
            day_midnight = cursor_wall.replace(hour=0, minute=0, second=0, microsecond=0)
            start_wall = day_midnight.replace(hour=start_time.hour, minute=start_time.minute)
            if is_any_time:
                end_wall = day_midnight + timedelta(days=1)
            else:
                end_wall = day_midnight.replace(hour=end_time.hour, minute=end_time.minute)

            effective_start = max(cursor_wall, start_wall)
            if effective_start < end_wall:
                available = (end_wall - effective_start).total_seconds() / 60.0
                if remaining <= available:
                    deadline_wall = effective_start + timedelta(minutes=remaining)
                    # Attach tz, normalize to UTC. Deterministic even at DST
                    # boundaries: zoneinfo resolves spring-forward gap times
                    # with the pre-transition offset, fall-back fold times
                    # with fold=0 (earlier occurrence). Both are stable; in
                    # practice deadlines rarely land in these windows.
                    return deadline_wall.replace(tzinfo=tz).astimezone(UTC)
                remaining -= available

        next_day = cursor_wall + timedelta(days=1)
        cursor_wall = next_day.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)

    raise ValueError(
        f"SLA amount is too large for the configured business hours (exceeded {_MAX_DAY_ITERATIONS}-day walk cap)"
    )
