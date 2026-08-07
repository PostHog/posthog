"""Scheduling math for per-check cadences.

Pure Python, no Django. Mirrors the approach in ``products/alerts/backend/scheduling.py``, kept
separate because checks have no calendar anchoring, quiet hours, or timezone rules -- just a
minute cadence spread across scanner ticks.
"""

from datetime import datetime, timedelta
from uuid import UUID

# How often the due-checks scanner fires. Offsets are quantized to this so a check never lands
# between ticks and waits a full extra period.
SCAN_INTERVAL_SECONDS = 300


def compute_shard_offset_seconds(
    check_id: UUID,
    interval_minutes: int,
    *,
    scan_interval_seconds: int = SCAN_INTERVAL_SECONDS,
) -> int:
    """Deterministic per-check offset within its cadence, so a fleet doesn't fire in one tick.

    ``check_id.int`` is stable across restarts, unlike process-local ``hash()``. Cadences at or
    below the scan interval get a single shard because there is nothing to spread them over.
    """
    shard_count = max(1, (interval_minutes * 60) // scan_interval_seconds)
    return (check_id.int % shard_count) * scan_interval_seconds


def advance_next_run_at(
    current_next_run_at: datetime | None,
    interval_minutes: int,
    now: datetime,
    *,
    shard_offset_seconds: int = 0,
) -> datetime:
    """Move to the next slot on the cadence grid, skipping any the scanner missed.

    Skipping rather than catching up matters after downtime: a check disabled for a day should run
    once when it comes back, not replay a day of missed ticks.
    """
    if interval_minutes <= 0:
        raise ValueError(f"interval_minutes must be positive, got {interval_minutes}")

    interval = timedelta(minutes=interval_minutes)
    next_at = (current_next_run_at + interval) if current_next_run_at else (now + interval)
    if next_at <= now:
        missed = int((now - next_at).total_seconds() // interval.total_seconds()) + 1
        next_at += interval * missed

    snapped = _floor_to_grid(next_at, interval_minutes) + timedelta(seconds=shard_offset_seconds)
    return snapped if snapped > now else snapped + interval


MINUTES_PER_DAY = 24 * 60


def _floor_to_grid(timestamp: datetime, cadence_minutes: int) -> datetime:
    """Snap onto the within-day cadence grid, so checks sharing a cadence share slots.

    Only meaningful for cadences that tile a day. A longer one (weekly, say) has no within-day grid
    to snap to, and flooring by minutes-into-day would collapse every timestamp onto midnight and
    turn a weekly check into a daily one.
    """
    if cadence_minutes >= MINUTES_PER_DAY:
        return timestamp.replace(second=0, microsecond=0)

    minutes_into_day = timestamp.hour * 60 + timestamp.minute
    floored = (minutes_into_day // cadence_minutes) * cadence_minutes
    return timestamp.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)
