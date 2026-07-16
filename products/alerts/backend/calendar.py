"""Calendar-anchored scheduling math for alert checks.

The second of the two scheduling models (see scheduling.py for grid cadence):
checks anchor to calendar instants in the team's local timezone, daily at 1am,
weekly Monday 3am, and monthly on the 1st at 4am, with quiet hours (blocked local
time windows) and weekend skipping layered on top.

Pure Python with no Django or model imports. Timezones are passed as IANA
names, quiet-hours windows as parsed tuples.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any

import pytz
from dateutil.relativedelta import relativedelta
from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError
from pytz.tzinfo import BaseTzInfo


class CalendarInterval(StrEnum):
    """Mirrors posthog.schema.AlertCalculationInterval values; wrappers convert."""

    REAL_TIME = "real_time"
    EVERY_15_MINUTES = "every_15_minutes"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


REAL_TIME_CADENCE_MINUTES = 2
EVERY_15_MINUTES_CADENCE_MINUTES = 15


def to_calendar_interval(value: str) -> CalendarInterval:
    try:
        return CalendarInterval(value)
    except ValueError:
        raise ValueError(f"Unhandled alert calculation interval: {value!r}") from None


def calendar_interval_to_relativedelta(interval: CalendarInterval) -> relativedelta:
    match interval:
        case CalendarInterval.REAL_TIME:
            return relativedelta(minutes=REAL_TIME_CADENCE_MINUTES)
        case CalendarInterval.EVERY_15_MINUTES:
            return relativedelta(minutes=EVERY_15_MINUTES_CADENCE_MINUTES)
        case CalendarInterval.HOURLY:
            return relativedelta(hours=1)
        case CalendarInterval.DAILY:
            return relativedelta(days=1)
        case CalendarInterval.WEEKLY:
            return relativedelta(weeks=1)
        case CalendarInterval.MONTHLY:
            return relativedelta(months=1)
        case _ as unreachable:
            raise ValueError(f"Unhandled alert calculation interval: {unreachable!r}")


def is_weekend(now: datetime, tz_name: str) -> bool:
    team_timezone = pytz.timezone(tz_name)
    now_local = now.astimezone(team_timezone)
    return now_local.isoweekday() in [6, 7]


def _localize_wall_time(team_timezone: BaseTzInfo, naive_local: datetime) -> datetime:
    try:
        return team_timezone.localize(naive_local, is_dst=None)
    except AmbiguousTimeError:
        return team_timezone.localize(naive_local, is_dst=True)
    except NonExistentTimeError:
        return team_timezone.normalize(team_timezone.localize(naive_local, is_dst=False))


def _calendar_anchor_utc(
    local_now: datetime,
    team_timezone: BaseTzInfo,
    *,
    target_date: date,
    hour: int,
) -> datetime:
    naive_local = datetime.combine(target_date, local_now.timetz().replace(tzinfo=None)).replace(hour=hour)
    return _localize_wall_time(team_timezone, naive_local).astimezone(UTC)


def next_calendar_check_time(
    interval: CalendarInterval,
    *,
    now: datetime,
    tz_name: str,
    next_check_at: datetime | None,
) -> datetime:
    """Nominal next check instant, before quiet-hours snapping.

    Sub-daily intervals advance from the previous next_check_at (falling back to
    now) so per-alert spread from creation time is preserved. Daily/weekly/monthly
    anchor to fixed local instants: 1am tomorrow, 3am next Monday, 4am on the 1st
    of next month. Hour-only replacement keeps the minute/second spread.
    """
    team_timezone = pytz.timezone(tz_name)
    local_now = now.astimezone(team_timezone)

    match interval:
        case CalendarInterval.REAL_TIME:
            return (next_check_at or now) + relativedelta(minutes=REAL_TIME_CADENCE_MINUTES)
        case CalendarInterval.EVERY_15_MINUTES:
            return (next_check_at or now) + relativedelta(minutes=EVERY_15_MINUTES_CADENCE_MINUTES)
        case CalendarInterval.HOURLY:
            return (next_check_at or now) + relativedelta(hours=1)
        case CalendarInterval.DAILY:
            return _calendar_anchor_utc(
                local_now,
                team_timezone,
                target_date=local_now.date() + timedelta(days=1),
                hour=1,
            )
        case CalendarInterval.WEEKLY:
            return _calendar_anchor_utc(
                local_now,
                team_timezone,
                target_date=local_now.date() + timedelta(days=7 - local_now.weekday()),
                hour=3,
            )
        case CalendarInterval.MONTHLY:
            if local_now.month == 12:
                target_date = date(local_now.year + 1, 1, 1)
            else:
                target_date = date(local_now.year, local_now.month + 1, 1)
            return _calendar_anchor_utc(local_now, team_timezone, target_date=target_date, hour=4)
        case _ as unreachable:
            raise ValueError(f"Unhandled alert calculation interval: {unreachable!r}")


# --- Quiet hours (blocked local time windows) ---

MAX_BLOCKED_WINDOWS = 5
MINUTES_PER_DAY = 1440
# Minimum length of each declared blocked window on the local daily timeline (half-open; same rules as expand).
MIN_BLOCKED_WINDOW_MINUTES = 30
# When quiet hours hit an unusual corner case, computing the next allowed send time must not
# run indefinitely or hold up other alerts; we cap how long we spend on that lookup.
MAX_UNBLOCK_STEPS = MINUTES_PER_DAY * 14

# (start_minute, end_minute, overnight)
BlockedWindow = tuple[int, int, bool]


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def normalize_schedule_restriction_value(raw: Any) -> dict[str, Any] | None:
    """Coerce payloads that mean 'off' to None. Returns dict ready to validate or None."""
    if raw is None:
        return None
    if raw == {}:
        return None
    if not isinstance(raw, dict):
        raise ValueError("schedule_restriction must be an object or null")
    windows = raw.get("blocked_windows")
    if windows is None:
        return None
    if windows == []:
        return None
    if not isinstance(windows, list):
        raise ValueError("blocked_windows must be an array")
    return raw


def _parse_hhmm(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError("Time must be a string HH:MM")
    s = value.strip()
    if s.count(":") != 1:
        raise ValueError("Time must be HH:MM (seconds not allowed)")
    parts = s.split(":")
    try:
        h = int(parts[0], 10)
        m = int(parts[1], 10)
    except ValueError as e:
        raise ValueError("Invalid HH:MM") from e
    if h < 0 or h > 23 or m < 0 or m > 59:
        raise ValueError("Invalid HH:MM")
    return h * 60 + m


def _parse_window_pair(start_s: str, end_s: str) -> BlockedWindow:
    start = _parse_hhmm(start_s)
    end = _parse_hhmm(end_s)
    if start == end:
        raise ValueError("Start and end must differ for a blocked window")
    overnight = start > end
    return start, end, overnight


def _blocked_window_span_minutes(start: int, end: int, overnight: bool) -> int:
    """Total minutes blocked in one local 24h cycle for this window (matches _expand_windows_for_coverage)."""
    if not overnight:
        return end - start
    if end == 0:
        return MINUTES_PER_DAY - start
    return (MINUTES_PER_DAY - start) + end


def _expand_windows_for_coverage(windows: list[BlockedWindow]) -> list[tuple[int, int]]:
    """Half-open intervals within [0, MINUTES_PER_DAY) for one synthetic day."""
    out: list[tuple[int, int]] = []
    for start, end, overnight in windows:
        if not overnight:
            if start < end:
                out.append((start, end))
            else:
                raise ValueError("Invalid window")
        else:
            if end == 0:
                # e.g. 19:00–00:00 = block from 19:00 through end of local calendar day (end exclusive at midnight)
                out.append((start, MINUTES_PER_DAY))
            else:
                out.append((start, MINUTES_PER_DAY))
                out.append((0, end))
    return out


def _merge_intervals_sorted(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: (x[0], x[1]))
    merged: list[tuple[int, int]] = []
    for a, b in intervals:
        if b <= a:
            continue
        if not merged or merged[-1][1] < a:
            merged.append((a, b))
        else:
            prev_a, prev_b = merged[-1]
            merged[-1] = (prev_a, max(prev_b, b))
    return merged


def merged_intervals_cover_full_day(merged: list[tuple[int, int]]) -> bool:
    return bool(merged) and merged[0][0] == 0 and merged[0][1] >= MINUTES_PER_DAY


def _encode_merged_to_blocked_windows(merged: list[tuple[int, int]]) -> list[dict[str, str]]:
    """Round-trip merged [0,1440) half-open segments to stored window dicts."""
    if not merged:
        return []
    if len(merged) == 1:
        a, b = merged[0]
        if a < b:
            if b == MINUTES_PER_DAY and a > 0:
                return [{"start": _hhmm(a), "end": "00:00"}]
            return [{"start": _hhmm(a), "end": _hhmm(b)}]
        raise ValueError("Invalid merged interval")
    if len(merged) == 2:
        a1, b1 = merged[0]
        a2, b2 = merged[1]
        # Overnight split into [0, morning_end) and [evening_start, 1440) after sorting by start
        if a1 == 0 and b2 == MINUTES_PER_DAY and a2 > b1:
            return [{"start": _hhmm(a2), "end": _hhmm(b1)}]
    out: list[dict[str, str]] = []
    for a, b in merged:
        if not a < b:
            continue
        if b == MINUTES_PER_DAY and a > 0:
            out.append({"start": _hhmm(a), "end": "00:00"})
        else:
            out.append({"start": _hhmm(a), "end": _hhmm(b)})
    return out


def validate_and_normalize_schedule_restriction(raw: Any) -> dict[str, Any] | None:
    """
    Validate API/store shape; merge overlaps on the daily timeline; return normalized dict or None.
    Raises ValueError on invalid input.
    """
    normalized_in = normalize_schedule_restriction_value(raw)
    if normalized_in is None:
        return None

    windows_in = normalized_in.get("blocked_windows")
    if not isinstance(windows_in, list):
        raise ValueError("blocked_windows must be an array")
    if len(windows_in) > MAX_BLOCKED_WINDOWS:
        raise ValueError(f"At most {MAX_BLOCKED_WINDOWS} blocked time windows are allowed")

    parsed: list[BlockedWindow] = []
    for idx, w in enumerate(windows_in):
        if not isinstance(w, dict):
            raise ValueError(f"blocked_windows[{idx}] must be an object")
        start_s = w.get("start")
        end_s = w.get("end")
        if start_s is None or end_s is None:
            raise ValueError(f"blocked_windows[{idx}] must have start and end (HH:MM)")
        start_i, end_i, overnight = _parse_window_pair(str(start_s), str(end_s))
        span = _blocked_window_span_minutes(start_i, end_i, overnight)
        if span < MIN_BLOCKED_WINDOW_MINUTES:
            raise ValueError(
                f"blocked_windows[{idx}] must span at least {MIN_BLOCKED_WINDOW_MINUTES} minutes "
                f"(half-open local window [start, end))"
            )
        parsed.append((start_i, end_i, overnight))

    expanded = _expand_windows_for_coverage(parsed)
    merged = _merge_intervals_sorted(expanded)
    if merged_intervals_cover_full_day(merged):
        raise ValueError("Leave at least one time in the day when this alert can run")

    encoded = _encode_merged_to_blocked_windows(merged)
    if not encoded:
        return None
    return {"blocked_windows": encoded}


def parse_blocked_windows_tuples(schedule_restriction: dict[str, Any] | None) -> list[BlockedWindow] | None:
    if not schedule_restriction:
        return None
    windows = schedule_restriction.get("blocked_windows")
    if not windows:
        return None
    out: list[BlockedWindow] = []
    for w in windows:
        if isinstance(w, dict) and "start" in w and "end" in w:
            out.append(_parse_window_pair(str(w["start"]), str(w["end"])))
    return out or None


def is_local_minute_blocked(minute: int, windows: list[BlockedWindow]) -> bool:
    for start, end, overnight in windows:
        if not overnight:
            if start <= minute < end:
                return True
        else:
            if end == 0:
                if minute >= start:
                    return True
            elif minute >= start or minute < end:
                return True
    return False


def _minute_of_local_datetime(dt_local: datetime) -> int:
    return dt_local.hour * 60 + dt_local.minute


def is_utc_datetime_blocked(dt_utc: datetime, tz_name: str, windows: list[BlockedWindow] | None) -> bool:
    if not windows:
        return False
    tz = pytz.timezone(tz_name)
    local = dt_utc.astimezone(tz).replace(second=0, microsecond=0)
    return is_local_minute_blocked(_minute_of_local_datetime(local), windows)


def scan_next_unblocked_utc(
    from_utc: datetime,
    tz_name: str,
    windows: list[BlockedWindow] | None,
    *,
    max_steps: int = MAX_UNBLOCK_STEPS,
) -> datetime | None:
    """Smallest UTC instant >= from_utc (minute precision) outside every blocked window.

    Returns None when no unblocked minute is found within max_steps. Callers own
    the fallback (insight alerts bump a day and retry, with logging).
    """
    if not windows:
        return from_utc.astimezone(UTC).replace(microsecond=0)

    tz = pytz.timezone(tz_name)
    cur = from_utc.astimezone(UTC).replace(second=0, microsecond=0)
    steps = 0
    while steps < max_steps:
        m = _minute_of_local_datetime(cur.astimezone(tz))
        if not is_local_minute_blocked(m, windows):
            return cur
        cur = cur + timedelta(minutes=1)
        steps += 1
    return None
