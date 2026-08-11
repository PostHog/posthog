"""Staged baseline selection: which past buckets are comparable to the scored one.

An exact time-of-week slot has only 3 observations after 3 weeks, so weekly
seasonality cannot be the starting model — the stage ladder widens the match
criteria for young series and narrows them as history accumulates:

* cold start: same day-type (weekday/weekend), same time of day ± pool
* developing: same weekday, same time of day ± pool
* mature: same time of week ± a small pool, across up to 12 weeks

Buckets are on a fixed UTC grid; time-of-week matching maps through the
project timezone so cron- and business-hour-shaped seasonality lines up with
local clocks. DST shift weeks are flagged so the detector can widen bands
(explicit reduced-confidence policy rather than silent misalignment).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.constants import BUCKET_MINUTES, BUCKETS_PER_DAY, BUCKETS_PER_WEEK
from products.apm.backend.logic.anomaly_detection.types import BaselineStage, SeriesHistory

MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY


@dataclass(frozen=True, slots=True)
class TimeGrid:
    """Per-bucket local-time attributes, computed once per (grid_start, length, tz)
    and shared across every series on the same grid."""

    start: datetime
    minute_of_day: np.ndarray
    weekday: np.ndarray
    minute_of_week: np.ndarray
    utc_offset_minutes: np.ndarray

    @classmethod
    def build(cls, grid_start: datetime, length: int, tz: ZoneInfo) -> TimeGrid:
        minute_of_day = np.empty(length, dtype=np.int32)
        weekday = np.empty(length, dtype=np.int8)
        utc_offset = np.empty(length, dtype=np.int32)
        for i in range(length):
            local = (grid_start + timedelta(minutes=BUCKET_MINUTES * i)).astimezone(tz)
            minute_of_day[i] = local.hour * 60 + local.minute
            weekday[i] = local.weekday()
            offset = local.utcoffset()
            utc_offset[i] = int(offset.total_seconds() // 60) if offset is not None else 0
        minute_of_week = weekday.astype(np.int32) * MINUTES_PER_DAY + minute_of_day
        return cls(
            start=grid_start,
            minute_of_day=minute_of_day,
            weekday=weekday,
            minute_of_week=minute_of_week,
            utc_offset_minutes=utc_offset,
        )

    def is_dst_shift_week(self, index: int) -> bool:
        week_ago = index - BUCKETS_PER_WEEK
        if week_ago < 0:
            return False
        return bool(self.utc_offset_minutes[index] != self.utc_offset_minutes[week_ago])


@dataclass(frozen=True, slots=True)
class BaselineResult:
    samples: np.ndarray
    stage: BaselineStage
    level_factor: float
    is_dst_shift_week: bool

    @property
    def scorable(self) -> bool:
        return self.stage is not BaselineStage.INSUFFICIENT


def _circular_diff(values: np.ndarray, target: int, period: int) -> np.ndarray:
    diff = np.abs(values - target)
    return np.minimum(diff, period - diff)


def _stage_for_age(age_buckets: int, config: DetectionConfig) -> BaselineStage:
    if age_buckets < config.min_history_buckets:
        return BaselineStage.INSUFFICIENT
    if age_buckets < config.cold_start_until_buckets:
        return BaselineStage.COLD_START
    if age_buckets < config.developing_until_buckets:
        return BaselineStage.DEVELOPING
    return BaselineStage.MATURE


# DST shifts local time-of-week by up to an hour relative to UTC grid stepping,
# so candidate supersets are padded by this many buckets before exact filtering.
_DST_SLACK_BUCKETS = 60 // BUCKET_MINUTES


def _stepped_positions(index: int, window_start: int, window_end: int, period: int, half_width: int) -> np.ndarray:
    """Superset of candidates at ``index - k*period ± half_width``, cheap to
    build (O(occurrences x pool) instead of O(window)) and filtered down to the
    exact time-of-week condition afterwards."""
    max_steps = (index - window_start) // period + 1
    steps = np.arange(0, max_steps + 1) * period
    offsets = np.arange(-half_width, half_width + 1)
    positions = np.unique(index - steps[:, None] + offsets[None, :])
    return positions[(positions >= window_start) & (positions < window_end)]


def _candidate_positions(
    grid: TimeGrid, index: int, window_start: int, window_end: int, stage: BaselineStage, config: DetectionConfig
) -> np.ndarray:
    if stage is BaselineStage.COLD_START:
        half_width = config.developing_pool_buckets + _DST_SLACK_BUCKETS
        positions = _stepped_positions(index, window_start, window_end, BUCKETS_PER_DAY, half_width)
        is_weekend = grid.weekday[positions] >= 5
        target_weekend = bool(grid.weekday[index] >= 5)
        time_match = (
            _circular_diff(grid.minute_of_day[positions], int(grid.minute_of_day[index]), MINUTES_PER_DAY)
            <= config.developing_pool_buckets * BUCKET_MINUTES
        )
        return positions[(is_weekend == target_weekend) & time_match]
    if stage is BaselineStage.DEVELOPING:
        half_width = config.developing_pool_buckets + _DST_SLACK_BUCKETS
        positions = _stepped_positions(index, window_start, window_end, BUCKETS_PER_WEEK, half_width)
        day_match = grid.weekday[positions] == grid.weekday[index]
        time_match = (
            _circular_diff(grid.minute_of_day[positions], int(grid.minute_of_day[index]), MINUTES_PER_DAY)
            <= config.developing_pool_buckets * BUCKET_MINUTES
        )
        return positions[day_match & time_match]
    half_width = config.mature_pool_buckets + _DST_SLACK_BUCKETS
    positions = _stepped_positions(index, window_start, window_end, BUCKETS_PER_WEEK, half_width)
    time_match = (
        _circular_diff(grid.minute_of_week[positions], int(grid.minute_of_week[index]), MINUTES_PER_WEEK)
        <= config.mature_pool_buckets * BUCKET_MINUTES
    )
    return positions[time_match]


def _apply_exclusions(candidates: np.ndarray, excluded: set[int], config: DetectionConfig) -> np.ndarray:
    if not excluded:
        return candidates
    excluded_sel = np.array(sorted(i for i in excluded if i in set(candidates.tolist())), dtype=candidates.dtype)
    if excluded_sel.size == 0:
        return candidates
    max_excludable = int(config.exclusion_cap_fraction * candidates.size)
    if excluded_sel.size > max_excludable:
        # Over the cap a permanent level shift is re-baselining itself: re-admit
        # the newest flagged buckets (the new level) and keep excluding the rest.
        readmit_count = excluded_sel.size - max_excludable
        readmitted = set(excluded_sel[-readmit_count:].tolist())
        excluded_sel = excluded_sel[:-readmit_count]
        drop = set(excluded_sel.tolist()) - readmitted
    else:
        drop = set(excluded_sel.tolist())
    return candidates[~np.isin(candidates, np.array(sorted(drop), dtype=candidates.dtype))]


def _level_factor(
    history: SeriesHistory, index: int, window_start: int, window_end: int, config: DetectionConfig
) -> float:
    if not config.level_adjustment_enabled:
        return 1.0
    recent_start = max(window_start, window_end - config.level_window_buckets)
    recent = history.counts[recent_start:window_end]
    reference = history.counts[window_start:window_end]
    if recent.size == 0 or reference.size == 0:
        return 1.0
    recent_mean = float(np.mean(recent))
    reference_mean = float(np.mean(reference))
    if reference_mean <= 0.0:
        return 1.0
    factor = recent_mean / reference_mean
    return float(np.clip(factor, 1.0 / config.level_factor_clamp, config.level_factor_clamp))


def candidate_slice_pad_buckets(config: DetectionConfig) -> int:
    """Half-width, in buckets, of the widest candidate pool any stage draws
    around a daily or weekly step from the evaluated bucket.

    A caller fetching sparse history (e.g. a just-in-time scan reading only the
    time slices baselines can sample) must pad each daily/weekly slice by this
    much per side to guarantee every position `_candidate_positions` can emit
    is backed by fetched data.
    """
    return max(config.developing_pool_buckets, config.mature_pool_buckets) + _DST_SLACK_BUCKETS


def select_baseline(
    history: SeriesHistory,
    index: int,
    grid: TimeGrid,
    config: DetectionConfig,
) -> BaselineResult:
    empty = np.array([], dtype=history.counts.dtype)
    first_active = history.first_active_index
    if first_active is None or first_active >= index:
        return BaselineResult(empty, BaselineStage.INSUFFICIENT, 1.0, False)

    age = index - first_active
    stage = _stage_for_age(age, config)
    if stage is BaselineStage.INSUFFICIENT:
        return BaselineResult(empty, stage, 1.0, False)

    window_start = max(first_active, index - config.max_lookback_buckets, history.baseline_floor_index)
    window_end = index - config.baseline_guard_buckets
    if window_end <= window_start:
        return BaselineResult(empty, BaselineStage.INSUFFICIENT, 1.0, False)
    candidates = _candidate_positions(grid, index, window_start, window_end, stage, config)
    candidates = _apply_exclusions(candidates, history.excluded, config)
    if candidates.size < config.min_baseline_samples:
        return BaselineResult(empty, BaselineStage.INSUFFICIENT, 1.0, False)

    level = _level_factor(history, index, window_start, window_end, config)
    samples = history.counts[candidates].astype(float)
    if level != 1.0:
        samples = samples * level
    return BaselineResult(samples, stage, level, grid.is_dst_shift_week(index))
