"""Load-spreading scheduler for data modeling (saved query) jobs.

Deterministic bucketing: Uses SHA-256 of entity_id + salt to derive
deterministic integers uniformly across all IDs

Frequency tiers:
- Short (15min, 30min, 1hr): ScheduleCalendarSpec with deterministic minute bucket + 1min jitter
- Medium (6hr, 12hr, 24hr): ScheduleCalendarSpec with deterministic hour bucket + 1hr jitter
- Weekly: ScheduleCalendarSpec with deterministic day (0-6) + hour (0-23) + 1hr jitter
- Monthly: ScheduleCalendarSpec with deterministic day (1-28) + hour (0-23) + 1hr jitter
"""

import uuid
import hashlib
from datetime import timedelta

from temporalio.client import ScheduleCalendarSpec, ScheduleRange, ScheduleSpec


def _deterministic_int(entity_id: uuid.UUID, salt: str) -> int:
    """SHA-256 based deterministic integer from entity_id + salt."""
    digest = hashlib.sha256(f"{entity_id}-{salt}".encode()).hexdigest()
    return int(digest[:16], 16)


def _short_interval_spec(entity_id: uuid.UUID, interval: timedelta, timezone: str) -> ScheduleSpec:
    """Short intervals (15min, 30min, 1hr): deterministic minute bucket + up to 1min jitter.

    Jitter spreads each run randomly within its assigned minute.
    """
    interval_mins = int(interval.total_seconds() // 60)
    num_windows = 60 // interval_mins
    base_min = _deterministic_int(entity_id, "minute") % interval_mins
    mins = [(base_min + i * interval_mins) % 60 for i in range(num_windows)]
    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                comment=f"Every {base_min}th minute in the {interval_mins}min interval window (bucketed)",
                hour=[ScheduleRange(start=0, end=23)],
                minute=[ScheduleRange(start=m, end=m) for m in mins],
            )
        ],
        jitter=timedelta(minutes=1),
        time_zone_name=timezone,
    )


def _medium_interval_spec(entity_id: uuid.UUID, interval: timedelta, timezone: str) -> ScheduleSpec:
    """Medium intervals (6hr, 12hr, 24hr): deterministic hour bucket + up to 1hr jitter.

    For a 6hr interval: pick 1 of 6 hour-buckets and repeat 4x per day -> 6 distinct buckets.
    For a 12hr interval: pick 1 of 12 hour-buckets and repeat 2x -> 12 distinct buckets.
    For a 24hr interval: pick 1 of 24 hour-buckets -> 24 distinct buckets.

    Jitter spreads each run randomly within its assigned hour.
    """
    interval_hours = int(interval.total_seconds() // 3600)
    num_windows = 24 // interval_hours
    base_hour = _deterministic_int(entity_id, "hour") % interval_hours
    hours = [(base_hour + i * interval_hours) % 24 for i in range(num_windows)]
    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                comment=f"Every {base_hour}th hour in the {interval_hours} interval window (bucketed)",
                hour=[ScheduleRange(start=h, end=h) for h in hours],
            )
        ],
        jitter=timedelta(hours=1),
        time_zone_name=timezone,
    )


def _weekly_spec(entity_id: uuid.UUID, timezone: str) -> ScheduleSpec:
    """Weekly schedule: deterministic day-of-week (0-6) + hour (0-23) + minute (0-59)."""
    day_of_week = _deterministic_int(entity_id, "day") % 7
    hour = _deterministic_int(entity_id, "hour") % 24

    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                comment="Weekly (load-spread)",
                day_of_week=[ScheduleRange(start=day_of_week, end=day_of_week)],
                hour=[ScheduleRange(start=hour, end=hour)],
            )
        ],
        jitter=timedelta(hours=1),
        time_zone_name=timezone,
    )


def _monthly_spec(entity_id: uuid.UUID, timezone: str) -> ScheduleSpec:
    """Monthly schedule: deterministic day-of-month (1-28) + hour (0-23) + minute (0-59)."""
    day_of_month = (_deterministic_int(entity_id, "day") % 28) + 1
    hour = _deterministic_int(entity_id, "hour") % 24

    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                comment="Monthly (load-spread)",
                day_of_month=[ScheduleRange(start=day_of_month, end=day_of_month)],
                hour=[ScheduleRange(start=hour, end=hour)],
            )
        ],
        jitter=timedelta(hours=1),
        time_zone_name=timezone,
    )


def build_schedule_spec(
    entity_id: uuid.UUID,
    interval: timedelta,
    team_timezone: str = "UTC",
) -> ScheduleSpec:
    """Build a Temporal ScheduleSpec for a saved query based on its sync frequency.

    Args:
        entity_id: The saved query UUID (used for deterministic bucketing).
        interval: The sync frequency interval (e.g. timedelta(hours=24)).
        team_timezone: The team's timezone (e.g. "America/New_York"). Used for 6hr+ schedules.

    Returns:
        A ScheduleSpec ready to be used with Temporal's Schedule API.
    """
    total_hours = interval.total_seconds() / 3600

    if total_hours <= 1:
        return _short_interval_spec(entity_id, interval, team_timezone)
    elif total_hours <= 24:
        return _medium_interval_spec(entity_id, interval, team_timezone)
    elif total_hours <= 168:
        return _weekly_spec(entity_id, team_timezone)
    else:
        return _monthly_spec(entity_id, team_timezone)
