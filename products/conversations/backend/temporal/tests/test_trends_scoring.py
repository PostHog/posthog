from __future__ import annotations

from datetime import datetime, timedelta

from parameterized import parameterized

from products.conversations.backend.temporal.trends.scoring import (
    SpikeConfig,
    floor_to_hour,
    score_builtin_volume,
    score_window,
)

# Fixed reference time; scoring only reads relative hourly offsets, never the wall clock.
NOW = datetime(2026, 7, 20, 14, 30, 0)
WINDOW_END = floor_to_hour(NOW)  # 14:00


def _flat_baseline(per_hour: int, *, hours: int = 24 * 30) -> dict[datetime, int]:
    """Every historical hour has the same count — a perfectly flat baseline."""
    return {WINDOW_END - timedelta(hours=i): per_hour for i in range(1, hours + 1)}


class TestScoreWindow:
    def test_spike_fires_over_flat_baseline(self) -> None:
        # Baseline of 2/hr, then 20 in the last hour: way over 3× and z is large.
        hourly = _flat_baseline(2)
        hourly[WINDOW_END - timedelta(hours=1)] = 20
        result = score_window(hourly, NOW, 1, SpikeConfig())
        assert result.fired
        assert result.observed == 20
        assert result.baseline_median == 2.0

    def test_no_spike_when_within_baseline(self) -> None:
        hourly = _flat_baseline(10)
        hourly[WINDOW_END - timedelta(hours=1)] = 11
        result = score_window(hourly, NOW, 1, SpikeConfig())
        assert not result.fired
        assert result.calm  # 11 < 1.5 * 10

    def test_mad_zero_requires_absolute_threshold(self) -> None:
        # Flat baseline of 1/hr → MAD is 0. A jump to 6 clears max(min_count=5, 3*1)=5.
        hourly = _flat_baseline(1)
        hourly[WINDOW_END - timedelta(hours=1)] = 6
        result = score_window(hourly, NOW, 1, SpikeConfig())
        assert result.fired
        assert result.zscore is None  # no dispersion to score against

    def test_mad_zero_below_absolute_floor_does_not_fire(self) -> None:
        hourly = _flat_baseline(1)
        hourly[WINDOW_END - timedelta(hours=1)] = 4  # below min_count=5
        result = score_window(hourly, NOW, 1, SpikeConfig())
        assert not result.fired

    def test_in_progress_hour_is_never_scored(self) -> None:
        # A huge count in the current (incomplete) hour must be ignored: only complete
        # hours strictly before WINDOW_END count.
        hourly = _flat_baseline(2)
        hourly[WINDOW_END] = 999
        result = score_window(hourly, NOW, 1, SpikeConfig())
        assert result.observed == 2  # the last complete hour, not the in-progress 999
        assert not result.fired

    def test_absolute_only_ignores_baseline(self) -> None:
        # No baseline sample considered; fires purely on min_count in the window.
        hourly = {WINDOW_END - timedelta(hours=1): 5}
        result = score_window(hourly, NOW, 1, SpikeConfig(min_count=5), absolute_only=True)
        assert result.fired
        assert result.baseline_median is None
        assert result.zscore is None

    def test_absolute_only_below_threshold(self) -> None:
        hourly = {WINDOW_END - timedelta(hours=1): 3}
        result = score_window(hourly, NOW, 1, SpikeConfig(min_count=5), absolute_only=True)
        assert not result.fired
        assert result.calm

    def test_two_hour_window_sums_two_complete_hours(self) -> None:
        hourly = _flat_baseline(1)
        hourly[WINDOW_END - timedelta(hours=1)] = 8
        hourly[WINDOW_END - timedelta(hours=2)] = 7
        result = score_window(hourly, NOW, 2, SpikeConfig())
        assert result.observed == 15


class TestScoreBuiltinVolume:
    def test_low_volume_falls_back_to_daily_window(self) -> None:
        # Under 20 tickets/week → single trailing-24h window instead of hourly.
        hourly: dict[datetime, int] = {}
        for day in range(1, 30):
            hourly[WINDOW_END - timedelta(days=day)] = 3
        # 24h ending now: put a burst spread over the last day.
        for hour in range(1, 25):
            hourly[WINDOW_END - timedelta(hours=hour)] = 5
        result = score_builtin_volume(hourly, NOW, trailing_week_total=10, config=SpikeConfig())
        assert result.window_minutes == 24 * 60

    @parameterized.expand(
        [
            ("one_hour_stronger", {1: 30, 2: 1}, 1 * 60),
            ("two_hour_stronger", {1: 8, 2: 40}, 2 * 60),
        ]
    )
    def test_reports_stronger_of_1h_and_2h(
        self, _name: str, recent: dict[int, int], expected_window_minutes: int
    ) -> None:
        hourly = _flat_baseline(2)
        for hours_ago, count in recent.items():
            hourly[WINDOW_END - timedelta(hours=hours_ago)] = count
        result = score_builtin_volume(hourly, NOW, trailing_week_total=400, config=SpikeConfig())
        assert result.fired
        assert result.window_minutes == expected_window_minutes
