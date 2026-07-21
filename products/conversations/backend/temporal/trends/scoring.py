"""Pure spike-scoring math for ticket trend/incident detection.

No I/O and no Django: callers fetch hourly ticket counts and pass them in,
which keeps every threshold decision unit-testable.

Method (mirroring the error-tracking spike detector and the anomaly-scout
conventions): the observed window count is compared against a
seasonality-matched baseline — the same window ending at the same clock time
on each of the trailing days — using a robust z-score,
``z = (x - median) / (1.4826 * MAD)``. A spike fires only when the count also
clears an absolute floor and a multiple of the median, so quiet series can't
alert off tiny wobbles.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

BASELINE_DAYS = 28
DEFAULT_Z_THRESHOLD = 4.0
DEFAULT_MULTIPLIER = 3.0
DEFAULT_MIN_COUNT = 5
# Below this many tickets in the trailing 7 days, hourly baselines are
# meaningless — switch to a single trailing-24h window.
LOW_VOLUME_WEEKLY_TOTAL = 20
# Relative detection needs at least this many real baseline samples. Fewer
# (young teams) and the sample is mostly phantom zeros from before the team's
# first ticket, which deflates the median and fires on perfectly normal volume.
MIN_BASELINE_DAYS = 7
# An active incident is "calm" once observed < CALM_FACTOR × baseline; after
# CALM_RUNS_TO_RESOLVE consecutive calm evaluations it auto-resolves.
CALM_FACTOR = 1.5
CALM_RUNS_TO_RESOLVE = 4
# Absolute backstop: resolve any incident still active after this long.
MAX_INCIDENT_AGE_HOURS = 24


@dataclass(frozen=True)
class SpikeConfig:
    min_count: int = DEFAULT_MIN_COUNT
    multiplier: float = DEFAULT_MULTIPLIER
    z_threshold: float = DEFAULT_Z_THRESHOLD


@dataclass(frozen=True)
class SpikeResult:
    fired: bool
    observed: int
    window_minutes: int
    # None when scored absolute-only (no baseline sample).
    baseline_median: float | None
    zscore: float | None
    # True when the observed count sits below the calm threshold — used to
    # advance an active incident toward auto-resolution.
    calm: bool


def floor_to_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _window_sum(hourly: Mapping[datetime, int], window_end: datetime, window_hours: int) -> int:
    """Sum of the ``window_hours`` complete hourly buckets ending at ``window_end`` (exclusive)."""
    return sum(hourly.get(window_end - timedelta(hours=i), 0) for i in range(1, window_hours + 1))


def _baseline_sample(
    hourly: Mapping[datetime, int],
    window_end: datetime,
    window_hours: int,
    baseline_days: int,
    history_start: datetime | None,
) -> list[int]:
    """Window sums ending at the same clock time on each of the prior ``baseline_days``
    days. Days whose window predates ``history_start`` (before the team's first ticket)
    are excluded — those zeros are absence of history, not genuine quiet."""
    samples = []
    for day in range(1, baseline_days + 1):
        sample_end = window_end - timedelta(days=day)
        if history_start is not None and sample_end - timedelta(hours=window_hours) < history_start:
            continue
        samples.append(_window_sum(hourly, sample_end, window_hours))
    return samples


def score_window(
    hourly: Mapping[datetime, int],
    now: datetime,
    window_hours: int,
    config: SpikeConfig,
    *,
    absolute_only: bool = False,
    baseline_days: int = BASELINE_DAYS,
    history_start: datetime | None = None,
) -> SpikeResult:
    """Score the trailing ``window_hours`` complete hours ending at the top of the
    current hour. The in-progress hour is never scored (partial buckets read as dips
    and their spikes are better caught one run later, complete).
    """
    window_end = floor_to_hour(now)
    observed = _window_sum(hourly, window_end, window_hours)
    window_minutes = window_hours * 60

    if absolute_only:
        fired = observed >= config.min_count
        return SpikeResult(
            fired=fired,
            observed=observed,
            window_minutes=window_minutes,
            baseline_median=None,
            zscore=None,
            calm=observed < config.min_count,
        )

    sample = _baseline_sample(hourly, window_end, window_hours, baseline_days, history_start)
    if len(sample) < MIN_BASELINE_DAYS:
        # Not enough history to say what "normal" looks like — never fire relative
        # detection for a young team; absolute-only rules still work.
        return SpikeResult(
            fired=False,
            observed=observed,
            window_minutes=window_minutes,
            baseline_median=None,
            zscore=None,
            calm=observed < config.min_count,
        )
    median = float(statistics.median(sample))
    mad = float(statistics.median([abs(value - median) for value in sample]))

    threshold = max(float(config.min_count), config.multiplier * max(median, 1.0))
    zscore: float | None = None
    if mad > 0:
        zscore = (observed - median) / (1.4826 * mad)
        fired = observed >= threshold and zscore >= config.z_threshold
    else:
        # A flat baseline gives no dispersion to score against; the absolute
        # threshold alone has to carry the decision.
        fired = observed >= threshold
    return SpikeResult(
        fired=fired,
        observed=observed,
        window_minutes=window_minutes,
        baseline_median=median,
        zscore=zscore,
        calm=observed < CALM_FACTOR * max(median, 1.0),
    )


def score_builtin_volume(
    hourly: Mapping[datetime, int],
    now: datetime,
    trailing_week_total: int,
    config: SpikeConfig,
    *,
    history_start: datetime | None = None,
) -> SpikeResult:
    """Built-in volume detection: score the last complete hour and the trailing
    2h window, reporting the stronger signal. Low-volume series fall back to a
    single trailing-24h window where hourly baselines would be all zeros.

    The low-volume baseline compares against the prior 28 daily windows rather
    than same-weekday windows: at this volume 28 samples beat the 4-8 weekday
    matches a same-weekday scheme could draw from the series we fetch, at the
    cost of some weekday-seasonality sensitivity.
    """
    if trailing_week_total < LOW_VOLUME_WEEKLY_TOTAL:
        return score_window(hourly, now, 24, config, history_start=history_start)

    one_hour = score_window(hourly, now, 1, config, history_start=history_start)
    two_hour = score_window(hourly, now, 2, config, history_start=history_start)
    return _stronger(one_hour, two_hour)


def _stronger(first: SpikeResult, second: SpikeResult) -> SpikeResult:
    """Prefer a fired result; between two fired results, the higher ratio over baseline."""
    if first.fired != second.fired:
        return first if first.fired else second

    def ratio(result: SpikeResult) -> float:
        return result.observed / max(result.baseline_median or 0.0, 1.0)

    return first if ratio(first) >= ratio(second) else second
