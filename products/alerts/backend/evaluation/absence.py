"""Detecting the buckets a series should have reported and didn't.

Some query runners return one row per bucket that *has data* — a metric that stops
being emitted simply stops producing rows rather than producing zeroes. A series
assembled from those rows therefore ends at the last healthy sample, so an alert
anchored on its tail keeps reading that stale value and goes quiet exactly when the
thing it watches dies.

This module names the complete buckets missing from the tail of such a series, so an
extractor can carry them as explicit points instead of letting the series end early.

The reporting cadence is inferred from the series itself, as the smallest gap between
consecutive observed buckets. That is the bucket width whenever any two adjacent
buckets reported, and for a metric that only reports every few buckets it reads as the
sparser cadence — so a sparse metric is judged against its own rhythm rather than the
grid's. A mean or max would be dragged upwards by interior gaps and under-report
absence; the minimum cannot be.

Pure Python: no Django, no product imports.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

# A series that stopped weeks ago would otherwise generate a padded point per bucket for
# the whole range. Callers only read the tail, so cap the work.
DEFAULT_MAX_PADDED_BUCKETS = 8


def _aware(value: dt.datetime) -> dt.datetime:
    """Bucket times render in the project timezone; a naive one is read as UTC."""
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def absent_trailing_buckets(
    bucket_times: Sequence[str],
    now: dt.datetime,
    *,
    max_buckets: int = DEFAULT_MAX_PADDED_BUCKETS,
) -> list[str]:
    """The complete buckets after the last observed one, in ascending order.

    ``bucket_times`` are ISO 8601 bucket starts, ascending. A bucket counts as missing
    only once it has closed (``start + cadence <= now``), so the still-accumulating
    bucket is never reported — it has no value yet, which is not the same as zero.

    Returns ``[]`` when the cadence cannot be inferred (fewer than two observed
    buckets). Padding on a guessed cadence could invent a breach, so this fails closed.
    """
    if len(bucket_times) < 2:
        return []

    parsed = [_aware(dt.datetime.fromisoformat(value)) for value in bucket_times]
    now = _aware(now)

    gaps = [later - earlier for earlier, later in zip(parsed, parsed[1:]) if later > earlier]
    if not gaps:
        return []
    cadence = min(gaps)

    absent: list[str] = []
    bucket = parsed[-1] + cadence
    while bucket + cadence <= now and len(absent) < max_buckets:
        absent.append(bucket.isoformat())
        bucket += cadence
    return absent
