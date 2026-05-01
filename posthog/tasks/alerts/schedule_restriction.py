"""Schedule restrictions (blocked local time windows) for insight alerts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytz
import structlog

from posthog.models import AlertConfiguration

logger = structlog.get_logger(__name__)

MAX_BLOCKED_WINDOWS = 5
MINUTES_PER_DAY = 1440
# Minimum length of each declared blocked window on the local daily timeline (half-open; same rules as expand).
MIN_BLOCKED_WINDOW_MINUTES = 30
# When quiet hours hit an unusual corner case, computing the next allowed send time must not
# run indefinitely or hold up other alerts; we cap how long we spend on that lookup.
_MAX_UNBLOCK_STEPS = MINUTES_PER_DAY * 14


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


def _parse_window_pair(start_s: str, end_s: str) -> tuple[int, int, bool]:
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


def _expand_windows_for_coverage(windows: list[tuple[int, int, bool]]) -> list[tuple[int, int]]:
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

    parsed: list[tuple[int, int, bool]] = []
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


def parse_blocked_windows_tuples(schedule_restriction: dict[str, Any] | None) -> list[tuple[int, int, bool]] | None:
    if not schedule_restriction:
        return None
    windows = schedule_restriction.get("blocked_windows")
    if not windows:
        return None
    out: list[tuple[int, int, bool]] = []
    for w in windows:
        if isinstance(w, dict) and "start" in w and "end" in w:
            out.append(_parse_window_pair(str(w["start"]), str(w["end"])))
    return out or None


def is_local_minute_blocked(minute: int, windows: list[tuple[int, int, bool]]) -> bool:
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


def is_utc_datetime_blocked(alert: AlertConfiguration, dt_utc: datetime) -> bool:
    windows = parse_blocked_windows_tuples(alert.schedule_restriction)
    if not windows:
        return False
    tz = pytz.timezone(alert.team.timezone)
    local = dt_utc.astimezone(tz).replace(second=0, microsecond=0)
    return is_local_minute_blocked(_minute_of_local_datetime(local), windows)


def next_unblocked_utc(alert: AlertConfiguration, from_utc: datetime) -> datetime:
    """Smallest UTC instant >= from_utc (minute precision) when the alert is not in a blocked window."""
    return _next_unblocked_utc(alert, from_utc, recursion_depth=0)


def _next_unblocked_utc(
    alert: AlertConfiguration,
    from_utc: datetime,
    *,
    recursion_depth: int,
) -> datetime:
    windows = parse_blocked_windows_tuples(alert.schedule_restriction)
    if not windows:
        return from_utc.astimezone(UTC).replace(microsecond=0)

    tz = pytz.timezone(alert.team.timezone)
    cur = from_utc.astimezone(tz).replace(second=0, microsecond=0)
    steps = 0
    while steps < _MAX_UNBLOCK_STEPS:
        m = _minute_of_local_datetime(cur)
        if not is_local_minute_blocked(m, windows):
            return cur.astimezone(pytz.UTC)
        cur = cur + timedelta(minutes=1)
        steps += 1

    logger.warning(
        "schedule_restriction.next_unblocked_utc_exceeded_cap",
        alert_id=str(alert.id),
        steps=steps,
        recursion_depth=recursion_depth,
    )
    if recursion_depth >= 1:
        logger.error(
            "schedule_restriction.next_unblocked_utc_giving_up_after_retry",
            alert_id=str(alert.id),
        )
        return (from_utc.astimezone(UTC) + timedelta(days=1)).replace(microsecond=0)

    bump = from_utc.astimezone(UTC) + timedelta(days=1)
    return _next_unblocked_utc(alert, bump, recursion_depth=recursion_depth + 1)


def snap_candidate_utc_to_schedule_restriction(alert: AlertConfiguration, candidate_utc: datetime) -> datetime:
    if not alert.schedule_restriction:
        return candidate_utc
    normalized = candidate_utc.astimezone(UTC).replace(second=0, microsecond=0)
    return next_unblocked_utc(alert, normalized)
