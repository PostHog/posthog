"""Window math for a source that checks M cadence-stepped rolling windows over freshly ingested data.

Pure Python with no Django or ClickHouse imports, so a source's event builders loaded at startup can use it.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Final

# Fall back to the scheduled time when the checkpoint is older than this. A quiet partition
# can pin `min(...)` hours behind while other partitions have fresh data.
CHECKPOINT_MAX_STALENESS: Final = dt.timedelta(minutes=5)

_THRESHOLD_OPERATORS: Final = frozenset({"above", "below"})


def rolling_check_lookback_minutes(window_minutes: int, cadence_minutes: int, period_count: int) -> int:
    """Total minutes of history covered by M cadence-stepped rolling windows."""
    return window_minutes + (period_count - 1) * cadence_minutes


def rolling_check_ranges(
    check_end: dt.datetime,
    window_minutes: int,
    cadence_minutes: int,
    period_count: int,
) -> list[tuple[dt.datetime, dt.datetime]]:
    """M cadence-stepped rolling windows ending at `check_end`, oldest-first."""
    ranges: list[tuple[dt.datetime, dt.datetime]] = []
    for k in range(period_count - 1, -1, -1):
        end = check_end - dt.timedelta(minutes=k * cadence_minutes)
        start = end - dt.timedelta(minutes=window_minutes)
        ranges.append((start, end))
    return ranges


def resolve_check_end(scheduled_at: dt.datetime, checkpoint: dt.datetime | None) -> dt.datetime:
    """Anchor the end of a check's windows on its scheduled time, clamped to the
    ingestion checkpoint when the checkpoint is fresh enough.

    Anchoring on the scheduled time (not wall-clock-now) is what makes the query
    window deterministic across retries and immune to scheduler lag — two evals
    of the same alert at different actual eval times produce the same end
    and thus the same query.
    """
    if checkpoint is None or (scheduled_at - checkpoint) > CHECKPOINT_MAX_STALENESS:
        return scheduled_at
    return min(scheduled_at, checkpoint)


def derive_breaches(
    counts: Sequence[float],
    threshold: float,
    threshold_operator: str,
    evaluation_periods: int,
) -> tuple[bool, ...]:
    """Map oldest-first window counts to a newest-first breach tuple of length M.

    `counts` holds one value per window from `rolling_check_ranges`, or nothing when the
    query returned no row for the alert or group. The state machine needs M data points
    regardless — so we pad the result to `evaluation_periods` with the implicit count=0 outcome:
    `False` for `above` (0 is never above a non-negative threshold), `True` for `below`
    (0 is below any threshold above 0).

    Without this pad, a `below` alert on a truly silent service would never
    fire — the query returns no row, the breach tuple is empty, and the N-of-M
    evaluator never sees the implicit "count is below threshold" signal.
    """
    if threshold_operator not in _THRESHOLD_OPERATORS:
        raise ValueError(f"Unknown threshold operator {threshold_operator!r}")
    if threshold_operator == "above":
        actual = tuple(count > threshold for count in reversed(counts))
        missing_breach = False
    else:
        actual = tuple(count < threshold for count in reversed(counts))
        missing_breach = True
    pad = (missing_breach,) * max(0, evaluation_periods - len(actual))
    return actual + pad
