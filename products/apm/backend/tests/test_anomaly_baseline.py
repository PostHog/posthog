from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

import numpy as np
from parameterized import parameterized

from products.apm.backend.logic.anomaly_detection.baseline import (
    MINUTES_PER_WEEK,
    TimeGrid,
    candidate_slice_pad_buckets,
    select_baseline,
)
from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.constants import BUCKET_MINUTES, BUCKETS_PER_DAY, BUCKETS_PER_WEEK
from products.apm.backend.logic.anomaly_detection.types import BaselineStage, SeriesHistory

GRID_START = datetime(2026, 1, 5, tzinfo=UTC)  # a Monday
GRID_LENGTH = 7 * BUCKETS_PER_WEEK
UTC_GRID = TimeGrid.build(GRID_START, GRID_LENGTH, ZoneInfo("UTC"))

NO_LEVEL_CONFIG = DetectionConfig(level_adjustment_enabled=False)


def make_history(counts: np.ndarray) -> SeriesHistory:
    return SeriesHistory(grid_start=GRID_START, counts=counts)


class TestStageLadder:
    @parameterized.expand(
        [
            ("too_young", 2 * BUCKETS_PER_DAY, BaselineStage.INSUFFICIENT),
            ("cold", 5 * BUCKETS_PER_DAY, BaselineStage.COLD_START),
            ("developing", 3 * BUCKETS_PER_WEEK, BaselineStage.DEVELOPING),
            ("mature", 6 * BUCKETS_PER_WEEK + 1, BaselineStage.MATURE),
        ]
    )
    def test_stage_follows_series_age(self, _name: str, age: int, expected: BaselineStage) -> None:
        counts = np.zeros(GRID_LENGTH)
        start = GRID_LENGTH - age - 1
        counts[start : GRID_LENGTH - 1] = 10.0
        result = select_baseline(make_history(counts), GRID_LENGTH - 1, UTC_GRID, NO_LEVEL_CONFIG)
        assert result.stage is expected


class TestSampleSelection:
    def test_developing_samples_come_from_the_same_weekday_and_time(self) -> None:
        counts = UTC_GRID.weekday.astype(float) + 10.0
        index = 4 * BUCKETS_PER_WEEK  # a Monday, age 4 weeks -> developing
        result = select_baseline(make_history(counts), index, UTC_GRID, NO_LEVEL_CONFIG)
        assert result.stage is BaselineStage.DEVELOPING
        assert set(np.unique(result.samples)) == {10.0 + UTC_GRID.weekday[index]}

    def test_mature_samples_come_from_the_same_time_of_week(self) -> None:
        counts = UTC_GRID.minute_of_week.astype(float)
        index = GRID_LENGTH - 1
        config = DetectionConfig(level_adjustment_enabled=False, developing_until_buckets=5 * BUCKETS_PER_DAY)
        result = select_baseline(make_history(counts), index, UTC_GRID, config)
        assert result.stage is BaselineStage.MATURE
        target = UTC_GRID.minute_of_week[index]
        linear = np.abs(result.samples - target)
        circular = np.minimum(linear, MINUTES_PER_WEEK - linear)
        assert np.all(circular <= config.mature_pool_buckets * BUCKET_MINUTES)

    def test_cold_start_pools_by_day_type(self) -> None:
        counts = np.where(UTC_GRID.weekday >= 5, 200.0, 50.0)
        counts[: GRID_LENGTH - 6 * BUCKETS_PER_DAY] = 0.0
        index = GRID_LENGTH - 1  # a Sunday
        result = select_baseline(make_history(counts), index, UTC_GRID, NO_LEVEL_CONFIG)
        assert result.stage is BaselineStage.COLD_START
        assert set(np.unique(result.samples)) == {200.0}

    def test_insufficient_when_fewer_than_min_samples(self) -> None:
        counts = np.full(GRID_LENGTH, 10.0)
        config = DetectionConfig(level_adjustment_enabled=False, min_baseline_samples=10_000)
        result = select_baseline(make_history(counts), GRID_LENGTH - 1, UTC_GRID, config)
        assert result.stage is BaselineStage.INSUFFICIENT


class TestExclusions:
    def test_excluded_buckets_leave_the_baseline(self) -> None:
        counts = np.full(GRID_LENGTH, 10.0)
        index = GRID_LENGTH - 1
        clean = select_baseline(make_history(counts), index, UTC_GRID, NO_LEVEL_CONFIG)
        history = make_history(counts.copy())
        poisoned = index - BUCKETS_PER_WEEK
        history.counts[poisoned] = 9_999.0
        history.excluded = {poisoned}
        result = select_baseline(history, index, UTC_GRID, NO_LEVEL_CONFIG)
        assert result.samples.size == clean.samples.size - 1
        assert 9_999.0 not in result.samples

    def test_exclusion_cap_readmits_newest_buckets_so_level_shifts_rebaseline(self) -> None:
        counts = np.full(GRID_LENGTH, 10.0)
        index = GRID_LENGTH - 1
        history = make_history(counts)
        all_candidates = select_baseline(history, index, UTC_GRID, NO_LEVEL_CONFIG).samples.size
        history.excluded = set(range(index))
        result = select_baseline(history, index, UTC_GRID, NO_LEVEL_CONFIG)
        assert result.stage is not BaselineStage.INSUFFICIENT
        assert result.samples.size >= int(all_candidates * NO_LEVEL_CONFIG.exclusion_cap_fraction)


class TestLevelFactor:
    def test_sustained_recent_level_scales_the_samples(self) -> None:
        counts = np.full(GRID_LENGTH, 10.0)
        index = GRID_LENGTH - 1
        counts[index - 2 * BUCKETS_PER_DAY : index] = 20.0
        config = DetectionConfig()
        result = select_baseline(make_history(counts), index, UTC_GRID, config)
        assert result.level_factor > 1.5
        assert float(np.median(result.samples)) > 10.0

    def test_level_factor_is_clamped(self) -> None:
        counts = np.full(GRID_LENGTH, 10.0)
        index = GRID_LENGTH - 1
        counts[index - 2 * BUCKETS_PER_DAY : index] = 10_000.0
        result = select_baseline(make_history(counts), index, UTC_GRID, DetectionConfig())
        assert result.level_factor == DetectionConfig().level_factor_clamp

    def test_level_ignores_change_inside_the_guard_window(self) -> None:
        counts = np.full(GRID_LENGTH, 10.0)
        index = GRID_LENGTH - 1
        config = DetectionConfig()
        counts[index - config.baseline_guard_buckets : index] = 10_000.0
        result = select_baseline(make_history(counts), index, UTC_GRID, config)
        assert result.level_factor == 1.0


class TestDst:
    def test_shift_week_is_flagged_in_project_timezone(self) -> None:
        tz = ZoneInfo("America/Los_Angeles")
        start = datetime(2026, 10, 12, tzinfo=UTC)  # DST ends 2026-11-01 in the US
        length = 4 * BUCKETS_PER_WEEK
        grid = TimeGrid.build(start, length, tz)
        before_shift = 1 * BUCKETS_PER_WEEK + 3 * BUCKETS_PER_DAY
        after_shift = 3 * BUCKETS_PER_WEEK
        assert not grid.is_dst_shift_week(before_shift)
        assert grid.is_dst_shift_week(after_shift)


DST_GRID_START = datetime(2026, 10, 5, tzinfo=UTC)  # a Monday; US DST ends 2026-11-01
DST_GRID_LENGTH = 5 * BUCKETS_PER_WEEK
DST_GRID = TimeGrid.build(DST_GRID_START, DST_GRID_LENGTH, ZoneInfo("America/Los_Angeles"))


class TestCandidateSlicePadding:
    # Evaluated after the DST shift, so local-time matching selects candidates
    # through the slack region beyond the pool — the padding guarantee's edge.
    @parameterized.expand(
        [
            (
                "cold_start",
                DetectionConfig(level_adjustment_enabled=False, cold_start_until_buckets=100 * BUCKETS_PER_WEEK),
                BaselineStage.COLD_START,
                BUCKETS_PER_DAY,
            ),
            ("developing", NO_LEVEL_CONFIG, BaselineStage.DEVELOPING, BUCKETS_PER_WEEK),
            (
                "mature",
                DetectionConfig(level_adjustment_enabled=False, developing_until_buckets=4 * BUCKETS_PER_WEEK),
                BaselineStage.MATURE,
                BUCKETS_PER_WEEK,
            ),
        ]
    )
    def test_samples_stay_within_padded_slices(
        self, _name: str, config: DetectionConfig, expected_stage: BaselineStage, step_buckets: int
    ) -> None:
        index = DST_GRID_LENGTH - 1
        counts = np.arange(DST_GRID_LENGTH, dtype=float) + 1.0  # value i+1 marks position i
        history = SeriesHistory(grid_start=DST_GRID_START, counts=counts)
        result = select_baseline(history, index, DST_GRID, config)
        assert result.stage is expected_stage
        assert result.samples.size > 0
        positions = result.samples - 1.0
        step_offset = (index - positions) % step_buckets
        distance = np.minimum(step_offset, step_buckets - step_offset)
        assert float(distance.max()) <= candidate_slice_pad_buckets(config)


class TestDetectionConfigValidation:
    @parameterized.expand([("zero", 0.0), ("default", 0.5), ("one", 1.0)])
    def test_accepts_fractional_exclusion_cap(self, _name: str, fraction: float) -> None:
        assert DetectionConfig(exclusion_cap_fraction=fraction).exclusion_cap_fraction == fraction

    @parameterized.expand([("negative", -0.1), ("above_one", 1.1), ("percent_style", 50.0)])
    def test_rejects_out_of_range_exclusion_cap(self, _name: str, fraction: float) -> None:
        with pytest.raises(ValueError, match="exclusion_cap_fraction"):
            DetectionConfig(exclusion_cap_fraction=fraction)
