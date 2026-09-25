"""Stable offsets that keep scheduled work off minute zero.

No schedule targets minute zero unless a customer was promised that instant. When every fleet
schedule fires at the top of the hour, the jobs pile up on the same ClickHouse cluster and each
query runs several times slower than it does alone. A job that reads the last interval needs only
the boundary plus ingestion lag, so it starts a few minutes after the boundary and spreads its work
across a window. Fleet schedules take a fixed minute (Celery beat, Dagster) or scheduler jitter
(Temporal). Work that fans out per alert, team, source or scanner takes an offset from this module:
the offset is the same for an entity on every run, and N entities spread evenly over the window,
so minute zero carries no more of them than any other minute.
The `schedule-must-avoid-minute-zero` semgrep rule enforces this for new schedules.
"""

import zlib
from datetime import timedelta


def deterministic_offset(key: str, window: timedelta, *, floor: timedelta = timedelta(0)) -> timedelta:
    """An offset in `[floor, floor + window)`, at one-second resolution, that depends only on `key`."""
    window_seconds = int(window.total_seconds())
    if window_seconds < 1:
        return floor
    # crc32, not hash(): Python salts str hashes per process, and the offset must be the same after a restart.
    return floor + timedelta(seconds=zlib.crc32(key.encode()) % window_seconds)
