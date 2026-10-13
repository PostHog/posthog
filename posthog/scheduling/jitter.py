"""Stable per-entity offsets for spreading scheduled work across a time window."""

import zlib
from datetime import timedelta


def deterministic_offset(key: str, window: timedelta, *, floor: timedelta = timedelta(0)) -> timedelta:
    """An offset in `[floor, floor + window)`, at one-second resolution, that depends only on `key`."""
    window_seconds = int(window.total_seconds())
    if window_seconds < 1:
        return floor
    # crc32, not hash(): Python salts str hashes per process, and the offset must be the same after a restart.
    return floor + timedelta(seconds=zlib.crc32(key.encode()) % window_seconds)
