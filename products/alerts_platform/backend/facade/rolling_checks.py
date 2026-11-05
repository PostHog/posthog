"""Window math for a source that checks M cadence-stepped rolling windows over freshly ingested data.

Pure Python with no Django or ClickHouse imports, so a source's event builders loaded at startup can use it.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Final

# Fall back to the scheduled time when the checkpoint is older than this. A quiet partition
# can pin `min(...)` hours behind while other partitions have fresh data.
CHECKPOINT_MAX_STALENESS: Final = dt.timedelta(minutes=5)


def rolling_check_lookback_minutes(window_minutes: int, cadence_minutes: int, period_count: int) -> int:
    """Total minutes of history covered by M cadence-stepped rolling windows."""
    return window_minutes + (period_count - 1) * cadence_minutes


def resolve_alert_date_to(nca: dt.datetime, checkpoint: dt.datetime | None) -> dt.datetime:
    """Anchor `date_to` on the alert's scheduled `next_check_at`, clamped to the
    ingestion checkpoint when the checkpoint is fresh enough.

    Anchoring on `next_check_at` (not wall-clock-now) is what makes the query
    window deterministic across retries and immune to scheduler lag — two evals
    of the same alert at different actual eval times produce the same `date_to`
    and thus the same query.
    """
    if checkpoint is None or (nca - checkpoint) > CHECKPOINT_MAX_STALENESS:
        return nca
    return min(nca, checkpoint)


def derive_breaches(
    counts: Sequence[float],
    threshold: float,
    threshold_operator: str,
    evaluation_periods: int,
) -> tuple[bool, ...]:
    """Map oldest-first window counts to a newest-first breach tuple of length M.

    A query that groups by window only emits windows that have data. The state machine needs M
    data points regardless of how sparse the underlying volume is — so we
    pad the result to `evaluation_periods` with the implicit count=0 outcome:
    `False` for `above` (0 is never above a non-negative threshold), `True` for `below`
    (0 is below any threshold above 0).

    Without this pad, a `below` alert on a truly silent service would never
    fire — the query returns no windows, the breach tuple is empty, and the N-of-M
    evaluator never sees the implicit "count is below threshold" signal.
    """
    if threshold_operator == "above":
        actual = tuple(count > threshold for count in reversed(counts))
        missing_breach = False
    else:
        actual = tuple(count < threshold for count in reversed(counts))
        missing_breach = True
    pad = (missing_breach,) * max(0, evaluation_periods - len(actual))
    return actual + pad
