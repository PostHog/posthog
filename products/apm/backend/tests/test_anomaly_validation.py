from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
from parameterized import parameterized

from products.apm.backend.logic.anomaly_detection.bands import PoissonBandModel
from products.apm.backend.logic.anomaly_detection.baseline import TimeGrid
from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.constants import BUCKETS_PER_DAY, BUCKETS_PER_WEEK
from products.apm.backend.logic.anomaly_detection.types import SeriesKey, TrafficTier
from products.apm.backend.logic.anomaly_detection.validation.harness import run_model, silence_gate_ablation
from products.apm.backend.logic.anomaly_detection.validation.simulation import (
    AnomalyKind,
    InjectedAnomaly,
    NegativeBinomialNoise,
    Scenario,
    SeasonalProfile,
    SeriesSpec,
    apply_anomaly,
    generate_counts,
    inject_anomalies,
    seasonal_multipliers,
)

GRID_START = datetime(2026, 1, 5, tzinfo=UTC)
GRID_LENGTH = 4 * BUCKETS_PER_WEEK
GRID = TimeGrid.build(GRID_START, GRID_LENGTH, ZoneInfo("UTC"))

CONFIG = DetectionConfig(
    min_history_buckets=BUCKETS_PER_DAY,
    cold_start_until_buckets=7 * BUCKETS_PER_DAY,
    developing_until_buckets=52 * BUCKETS_PER_WEEK,
    persistence_window_buckets=BUCKETS_PER_DAY,
    persistence_recent_buckets=24,
    level_adjustment_enabled=False,
)


def make_spec(**overrides: object) -> SeriesSpec:
    defaults: dict = {
        "key": SeriesKey(namespace="default", service="svc", environment="production", severity="info"),
        "tier": TrafficTier.A,
        "profile": SeasonalProfile.FLAT,
        "mean_per_bucket": 200.0,
        "cv": 0.12,
    }
    defaults.update(overrides)
    return SeriesSpec(**defaults)


class TestGenerator:
    @parameterized.expand(
        [
            ("tier_a_info", 1_500.0, 0.12),
            ("tier_b_info", 60.0, 0.35),
            ("error_overdispersed", 6.0, 2.2),
        ]
    )
    def test_counts_match_target_mean_and_cv(self, _name: str, mean: float, cv: float) -> None:
        spec = make_spec(mean_per_bucket=mean, cv=cv)
        counts = generate_counts(spec, GRID, np.random.default_rng(3))
        observed_mean = float(np.mean(counts))
        observed_cv = float(np.std(counts) / observed_mean)
        assert abs(observed_mean - mean) / mean < 0.15
        assert abs(observed_cv - cv) / cv < 0.35

    def test_ephemeral_series_is_zero_outside_lifetime(self) -> None:
        spec = make_spec(birth_index=100, death_index=200, mean_per_bucket=50.0)
        counts = generate_counts(spec, GRID, np.random.default_rng(3))
        assert np.all(counts[:100] == 0)
        assert np.all(counts[200:] == 0)
        assert np.any(counts[100:200] > 0)

    @parameterized.expand([(SeasonalProfile.DIURNAL, 1.8), (SeasonalProfile.CRON, 5.0)])
    def test_seasonal_profiles_have_the_measured_shape(self, profile: SeasonalProfile, min_ratio: float) -> None:
        multipliers = seasonal_multipliers(profile, GRID)
        assert float(np.max(multipliers) / np.min(multipliers)) >= min_ratio
        assert abs(float(np.mean(multipliers)) - 1.0) < 0.01

    def test_weekend_peak_profile_peaks_on_saturday(self) -> None:
        multipliers = seasonal_multipliers(SeasonalProfile.WEEKEND_PEAK, GRID)
        saturday = multipliers[GRID.weekday == 5]
        weekday = multipliers[GRID.weekday < 5]
        assert float(np.min(saturday)) > float(np.max(weekday))

    def test_overdispersed_noise_actually_exceeds_poisson_variance(self) -> None:
        rng = np.random.default_rng(3)
        means = np.full(5_000, 20.0)
        counts = NegativeBinomialNoise().sample(rng, means, cv=2.0)
        assert float(np.var(counts)) > 3 * float(np.mean(counts))


class TestInjection:
    def test_injection_modifies_counts_and_registers_truth(self) -> None:
        spec = make_spec()
        rng = np.random.default_rng(5)
        scenario = Scenario(specs=[spec], counts={spec.key: generate_counts(spec, GRID, rng)})
        eval_start = GRID_LENGTH - BUCKETS_PER_WEEK
        inject_anomalies(scenario, rng, eval_start, GRID_LENGTH, 1, 1, 1)
        assert len(scenario.anomalies) == 3
        silence = next(a for a in scenario.anomalies if a.kind is AnomalyKind.SILENCE)
        assert np.all(scenario.counts[spec.key][silence.start : silence.end] == 0)
        assert scenario.truth_at(spec.key, silence.start) is silence
        assert scenario.truth_at(spec.key, eval_start - 1) is None


class TestHarness:
    def test_detector_finds_injected_anomalies_on_a_clean_series(self) -> None:
        spec = make_spec()
        rng = np.random.default_rng(11)
        scenario = Scenario(specs=[spec], counts={spec.key: generate_counts(spec, GRID, rng)})
        eval_start = GRID_LENGTH - BUCKETS_PER_WEEK
        inject_anomalies(scenario, rng, eval_start, GRID_LENGTH, 2, 1, 1)
        report = run_model(scenario, GRID, CONFIG, PoissonBandModel(), eval_start, GRID_LENGTH)
        group = report.groups[(TrafficTier.A, "info")]
        assert group.window_recall == 1.0
        assert report.issues.opens_total >= 1

    def test_persistence_gate_suppresses_dead_pod_silence(self) -> None:
        eval_start_index = GRID_LENGTH - BUCKETS_PER_WEEK
        # Alive long enough to pass the baseline min-history and floor gates —
        # for shorter-lived pods those suppress silence with or without the
        # persistence gate, so the gate's marginal effect is on the death side.
        pod = make_spec(
            key=SeriesKey(namespace="default", service="pod-1", environment="production", severity="info"),
            tier=TrafficTier.C,
            mean_per_bucket=20.0,
            cv=0.5,
            birth_index=eval_start_index - 2 * BUCKETS_PER_DAY,
            death_index=eval_start_index + BUCKETS_PER_DAY // 2,
        )
        steady = make_spec()
        rng = np.random.default_rng(13)
        scenario = Scenario(
            specs=[steady, pod],
            counts={s.key: generate_counts(s, GRID, rng) for s in (steady, pod)},
        )
        eval_start = GRID_LENGTH - BUCKETS_PER_WEEK
        ablation = silence_gate_ablation(scenario, GRID, CONFIG, PoissonBandModel(), eval_start, GRID_LENGTH)
        with_gate = ablation["full design"]
        without_gate = ablation["no persistence gate"]
        # A multi-day pod's death is indistinguishable from a dead worker at
        # death time (the characterization's residual FP), so the gate's
        # contract is bounding the firing window, not eliminating it.
        assert with_gate.silence_fp_ephemeral <= CONFIG.persistence_recent_buckets
        assert without_gate.silence_fp_ephemeral >= 5 * max(with_gate.silence_fp_ephemeral, 1)

    def test_level_shifted_series_is_excluded_from_precision_metrics(self) -> None:
        spec = make_spec()
        rng = np.random.default_rng(17)
        counts = generate_counts(spec, GRID, rng)
        shift = InjectedAnomaly(spec.key, AnomalyKind.LEVEL_SHIFT, GRID_LENGTH - BUCKETS_PER_WEEK, GRID_LENGTH, 2.0)
        apply_anomaly(counts, shift)
        scenario = Scenario(specs=[spec], counts={spec.key: counts}, anomalies=[shift])
        report = run_model(scenario, GRID, CONFIG, PoissonBandModel(), GRID_LENGTH - BUCKETS_PER_WEEK, GRID_LENGTH)
        assert report.groups == {}
