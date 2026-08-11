from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
from parameterized import parameterized

from products.apm.backend.logic.anomaly_detection.bands import PoissonBandModel
from products.apm.backend.logic.anomaly_detection.baseline import TimeGrid
from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.constants import BUCKETS_PER_DAY
from products.apm.backend.logic.anomaly_detection.detector import (
    evaluate_series_bucket,
    evaluate_series_bucket_detail,
    evaluate_tick,
    traffic_tier,
)
from products.apm.backend.logic.anomaly_detection.types import (
    BaselineStage,
    SeriesHistory,
    SeriesKey,
    TrafficTier,
    VerdictType,
)

GRID_START = datetime(2026, 1, 5, tzinfo=UTC)
GRID_LENGTH = 15 * BUCKETS_PER_DAY
GRID = TimeGrid.build(GRID_START, GRID_LENGTH, ZoneInfo("UTC"))
INDEX = GRID_LENGTH - 1

# Pins every full-history series at DEVELOPING: same-weekday matching works
# inside a 15-day grid, where MATURE would need same time-of-week from prior
# weeks and COLD_START would widen the bands under test.
CONFIG = DetectionConfig(
    min_history_buckets=BUCKETS_PER_DAY,
    cold_start_until_buckets=2 * BUCKETS_PER_DAY,
    developing_until_buckets=30 * BUCKETS_PER_DAY,
    persistence_window_buckets=BUCKETS_PER_DAY,
    persistence_recent_buckets=24,
    expiry_buckets=BUCKETS_PER_DAY,
    level_adjustment_enabled=False,
)

KEY = SeriesKey(namespace="prod", service="checkout", environment="us", severity="info")
MODEL = PoissonBandModel(rate_floor=CONFIG.band_rate_floor)


def steady_history(rate: float = 100.0) -> SeriesHistory:
    return SeriesHistory(grid_start=GRID_START, counts=np.full(GRID_LENGTH, rate))


def evaluate(history: SeriesHistory, index: int = INDEX) -> VerdictType | None:
    verdict = evaluate_series_bucket(history, index, KEY, GRID, CONFIG, MODEL)
    return verdict.verdict_type if verdict else None


class TestVerdicts:
    @parameterized.expand(
        [
            ("normal_bucket", 100.0, None),
            ("spike", 1_000.0, VerdictType.SPIKE),
            ("drop", 20.0, VerdictType.DROP),
            ("silence", 0.0, VerdictType.SILENCE),
        ]
    )
    def test_observed_vs_steady_baseline(self, _name: str, observed: float, expected: VerdictType | None) -> None:
        history = steady_history()
        history.counts[INDEX] = observed
        assert evaluate(history) is expected

    def test_ongoing_incident_does_not_legitimize_itself(self) -> None:
        history = steady_history()
        history.counts[INDEX - 100 :] = 1_000.0
        assert evaluate(history) is VerdictType.SPIKE

    def test_severity_multiplier_widens_the_band(self) -> None:
        history = steady_history()
        history.counts[INDEX] = 145.0
        assert evaluate(history) is VerdictType.SPIKE
        widened_config = replace(CONFIG, severity_variance_multipliers={"error": 4.0})
        error_key = SeriesKey(namespace="prod", service="checkout", environment="us", severity="error")
        verdict = evaluate_series_bucket(history, INDEX, error_key, GRID, widened_config, MODEL)
        assert verdict is None


class TestGates:
    def test_young_series_gets_no_verdict_even_on_a_huge_spike(self) -> None:
        history = steady_history()
        history.counts[: INDEX - CONFIG.persistence_window_buckets + 10] = 0.0
        history.counts[INDEX] = 10_000.0
        assert evaluate(history) is None

    def test_dead_ephemeral_pod_is_not_a_silent_service(self) -> None:
        history = steady_history()
        death = INDEX - CONFIG.persistence_recent_buckets - 10
        history.counts[death:] = 0.0
        assert evaluate(history) is None

    def test_recently_quiet_persistent_series_is_silence(self) -> None:
        history = steady_history()
        history.counts[INDEX - 3 :] = 0.0
        assert evaluate(history) is VerdictType.SILENCE

    def test_expired_series_leaves_coverage(self) -> None:
        history = steady_history()
        history.counts[INDEX - CONFIG.expiry_buckets - 5 :] = 0.0
        assert evaluate(history) is None

    def test_sub_floor_series_is_not_scored(self) -> None:
        history = steady_history(rate=2.0)
        history.counts[INDEX] = 50.0
        assert evaluate(history) is None

    def test_overnight_quiet_hours_cannot_fire_silence(self) -> None:
        hour_of_day = (GRID.minute_of_day // 60).astype(float)
        counts = np.where((hour_of_day >= 8) & (hour_of_day < 20), 100.0, 0.0)
        history = SeriesHistory(grid_start=GRID_START, counts=counts)
        night_index = INDEX - 2  # 23:45 UTC — learned rate ~0
        assert history.counts[night_index] == 0.0
        assert evaluate(history, night_index) is None


class TestTiers:
    @parameterized.expand(
        [
            (200.0, TrafficTier.A),
            (50.0, TrafficTier.B),
            (10.0, TrafficTier.C),
            (1.0, TrafficTier.D),
        ]
    )
    def test_tier_from_trailing_rate(self, rate: float, expected: TrafficTier) -> None:
        assert traffic_tier(steady_history(rate), INDEX, CONFIG) is expected


class TestEvaluateDetail:
    def test_in_band_bucket_still_reports_band_stage_and_tier(self) -> None:
        detail = evaluate_series_bucket_detail(steady_history(), INDEX, KEY, GRID, CONFIG, MODEL)
        assert detail.verdict is None
        assert detail.band is not None
        assert detail.band.lower <= detail.observed <= detail.band.upper
        assert detail.stage is BaselineStage.DEVELOPING
        assert detail.tier is TrafficTier.B

    def test_gated_bucket_reports_observed_only(self) -> None:
        history = steady_history(rate=2.0)  # below the traffic floor
        history.counts[INDEX] = 50.0
        detail = evaluate_series_bucket_detail(history, INDEX, KEY, GRID, CONFIG, MODEL)
        assert detail.observed == 50.0
        assert detail.band is None
        assert detail.stage is None
        assert detail.tier is None
        assert detail.verdict is None


class TestEvaluateTick:
    def test_returns_verdicts_for_anomalous_series_only(self) -> None:
        quiet = steady_history()
        spiking = steady_history()
        spiking.counts[INDEX] = 10_000.0
        other_key = SeriesKey(namespace="prod", service="worker", environment="us", severity="info")
        verdicts = evaluate_tick({KEY: quiet, other_key: spiking}, INDEX, GRID, CONFIG, MODEL)
        assert [(v.key, v.verdict_type) for v in verdicts] == [(other_key, VerdictType.SPIKE)]
