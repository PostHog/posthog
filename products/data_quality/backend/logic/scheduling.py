"""Scheduling math for per-check cadences.

Pure Python, no Django. Mirrors the approach in ``products/alerts/backend/scheduling.py``, kept
separate because checks have no calendar anchoring, quiet hours, or timezone rules -- just a
minute cadence spread across scanner ticks.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

# How often the due-checks scanner fires. Offsets are quantized to this so a check never lands
# between ticks and waits a full extra period.
SCAN_INTERVAL_SECONDS = 300

# Every cadence grid is anchored at this fixed epoch, so its slots sit at ANCHOR + offset +
# k * interval. Two checks sharing a cadence and offset therefore share slots regardless of when
# either was created, the phase offset is baked into the grid once instead of re-added on every
# advance, and a cadence that does not divide a day keeps its spacing across midnight.
_GRID_ANCHOR = datetime(1970, 1, 1, tzinfo=UTC)


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
    interval_minutes: int,
    now: datetime,
    *,
    shard_offset_seconds: int = 0,
) -> datetime:
    """The next slot on the phased cadence grid strictly after ``now``.

    The result is a pure function of the cadence, the offset, and ``now`` -- never of the previous
    ``next_run_at`` -- because the grid is anchored at a fixed epoch. Computing the slot directly
    rather than adding an interval to the last one keeps the offset applied exactly once (advancing
    an already-phased slot yields the following slot, not a doubly-offset one) and skips windows
    missed during downtime rather than replaying them: a check disabled for a day runs once when it
    comes back, not once per missed tick.
    """
    if interval_minutes <= 0:
        raise ValueError(f"interval_minutes must be positive, got {interval_minutes}")

    interval = timedelta(minutes=interval_minutes)
    anchor = _GRID_ANCHOR + timedelta(seconds=shard_offset_seconds)
    slots_elapsed = (now - anchor) // interval
    return anchor + (slots_elapsed + 1) * interval
