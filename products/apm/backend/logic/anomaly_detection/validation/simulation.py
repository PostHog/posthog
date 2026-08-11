"""Seeded series generator: production-shaped noise, synthetic anomalies.

A simulation fed synthetic Poisson noise would validate our assumptions
against themselves (and confidently report that a Poisson detector works).
Instead the generator is seeded with tier medians, per-severity CVs,
empty-bucket rates, and seasonal profiles calibrated to an internal
characterization of production log workloads — real noise, known answers. Injected anomalies provide the ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import numpy as np

from products.apm.backend.logic.anomaly_detection.baseline import TimeGrid
from products.apm.backend.logic.anomaly_detection.constants import BUCKETS_PER_DAY
from products.apm.backend.logic.anomaly_detection.types import Direction, SeriesKey, TrafficTier
from products.apm.backend.logic.anomaly_detection.validation import calibration

MINUTES_PER_DAY = 24 * 60


class SeasonalProfile(StrEnum):
    FLAT = "flat"
    DIURNAL = "diurnal"
    CRON = "cron"
    WEEKEND_PEAK = "weekend_peak"


class AnomalyKind(StrEnum):
    SPIKE = "spike"
    DROP = "drop"
    SILENCE = "silence"
    LEVEL_SHIFT = "level_shift"


ANOMALY_DIRECTION: dict[AnomalyKind, Direction] = {
    AnomalyKind.SPIKE: Direction.UP,
    AnomalyKind.DROP: Direction.DOWN,
    AnomalyKind.SILENCE: Direction.DOWN,
    AnomalyKind.LEVEL_SHIFT: Direction.UP,
}


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    key: SeriesKey
    tier: TrafficTier
    profile: SeasonalProfile
    mean_per_bucket: float
    cv: float
    empty_bucket_rate: float = 0.0
    birth_index: int = 0
    death_index: int | None = None

    @property
    def is_ephemeral(self) -> bool:
        return self.death_index is not None


@dataclass(frozen=True, slots=True)
class InjectedAnomaly:
    key: SeriesKey
    kind: AnomalyKind
    start: int
    end: int  # exclusive
    factor: float

    @property
    def direction(self) -> Direction:
        return ANOMALY_DIRECTION[self.kind]

    def contains(self, index: int) -> bool:
        return self.start <= index < self.end


@dataclass(slots=True)
class Scenario:
    specs: list[SeriesSpec]
    counts: dict[SeriesKey, np.ndarray]
    anomalies: list[InjectedAnomaly] = field(default_factory=list)

    def truth_at(self, key: SeriesKey, index: int) -> InjectedAnomaly | None:
        for anomaly in self.anomalies:
            if anomaly.key == key and anomaly.contains(index):
                return anomaly
        return None


class NoiseModel(Protocol):
    def sample(self, rng: np.random.Generator, means: np.ndarray, cv: float) -> np.ndarray: ...


class NegativeBinomialNoise:
    """Counts with a target CV: negative binomial when overdispersed relative
    to Poisson, Poisson otherwise. The default NoiseModel — swappable so a
    design partner's measured distributions can replace it."""

    def sample(self, rng: np.random.Generator, means: np.ndarray, cv: float) -> np.ndarray:
        counts = np.zeros(means.shape, dtype=np.int64)
        positive = means > 0
        mu = means[positive]
        var = (cv * mu) ** 2
        overdispersed = var > mu * 1.001
        out = np.empty(mu.shape, dtype=np.int64)
        if np.any(overdispersed):
            mu_od = mu[overdispersed]
            var_od = var[overdispersed]
            r = mu_od**2 / (var_od - mu_od)
            p = r / (r + mu_od)
            out[overdispersed] = rng.negative_binomial(r, p)
        if np.any(~overdispersed):
            out[~overdispersed] = rng.poisson(mu[~overdispersed])
        counts[positive] = out
        return counts


def seasonal_multipliers(profile: SeasonalProfile, grid: TimeGrid) -> np.ndarray:
    hours = grid.minute_of_day / 60.0
    if profile is SeasonalProfile.FLAT:
        ratio = calibration.FLAT_PEAK_TROUGH
        shape = 1.0 + (ratio - 1.0) / 2.0 * np.sin(2 * np.pi * (hours - 9.0) / 24.0)
    elif profile is SeasonalProfile.DIURNAL:
        ratio = calibration.DIURNAL_PEAK_TROUGH
        trough = 2.0 / (1.0 + ratio)
        peak = trough * ratio
        shape = trough + (peak - trough) * (0.5 + 0.5 * np.sin(2 * np.pi * (hours - 9.0) / 24.0))
    elif profile is SeasonalProfile.CRON:
        shape = np.ones(grid.minute_of_day.shape)
        in_step = np.isin(grid.minute_of_day // 60, calibration.CRON_STEP_HOURS)
        shape[in_step] = calibration.CRON_STEP_FACTOR
    else:  # WEEKEND_PEAK — the measured Saturday-peaking service
        shape = np.where(grid.weekday == 5, calibration.WEEKEND_PEAK_FACTOR, 1.0)
    return shape / float(np.mean(shape))


def generate_counts(
    spec: SeriesSpec,
    grid: TimeGrid,
    rng: np.random.Generator,
    noise: NoiseModel | None = None,
) -> np.ndarray:
    noise = noise or NegativeBinomialNoise()
    means = spec.mean_per_bucket * seasonal_multipliers(spec.profile, grid)
    counts = noise.sample(rng, means, spec.cv)
    if spec.empty_bucket_rate > 0:
        counts[rng.random(counts.shape) < spec.empty_bucket_rate] = 0
    counts[: spec.birth_index] = 0
    if spec.death_index is not None:
        counts[spec.death_index :] = 0
    return counts


def apply_anomaly(counts: np.ndarray, anomaly: InjectedAnomaly) -> None:
    window = slice(anomaly.start, anomaly.end)
    if anomaly.kind is AnomalyKind.SILENCE:
        counts[window] = 0
    elif anomaly.kind is AnomalyKind.LEVEL_SHIFT:
        counts[anomaly.start :] = np.round(counts[anomaly.start :] * anomaly.factor)
    else:
        counts[window] = np.round(counts[window] * anomaly.factor)


def _series_key(service: str, severity: str) -> SeriesKey:
    return SeriesKey(namespace="default", service=service, environment="production", severity=severity)


def build_population(
    grid_length: int,
    rng: np.random.Generator,
    ephemeral_count: int = 30,
    young_births: tuple[int, ...] = (),
) -> list[SeriesSpec]:
    """Persistent services across tiers/profiles/severities, plus the ephemeral
    pod population that makes the persistence-gate ablation meaningful.

    young_births adds persistent services born mid-timeline so the eval
    window contains cold-start and developing-stage series — per-stage metrics
    are meaningless if every series is mature by eval time."""
    tiers = calibration.TIER_CALIBRATION
    specs: list[SeriesSpec] = []

    for profile in (SeasonalProfile.FLAT, SeasonalProfile.DIURNAL, SeasonalProfile.CRON, SeasonalProfile.WEEKEND_PEAK):
        service = f"svc-a-{profile.value}"
        a = tiers[TrafficTier.A]
        specs.append(
            SeriesSpec(
                _series_key(service, "info"), TrafficTier.A, profile, a.median_per_bucket, a.cv, a.empty_bucket_rate
            )
        )
        # Severity mix puts warn at ~10% and error at ~0.5% of info volume;
        # error carries the measured overdispersion (CV 2.2).
        specs.append(
            SeriesSpec(_series_key(service, "warn"), TrafficTier.B, profile, a.median_per_bucket * 0.10, 0.35, 0.01)
        )
        specs.append(
            SeriesSpec(
                _series_key(service, "error"),
                TrafficTier.C,
                profile,
                a.median_per_bucket * 0.005,
                calibration.ERROR_CV,
                0.05,
            )
        )

    for profile in (SeasonalProfile.FLAT, SeasonalProfile.DIURNAL, SeasonalProfile.CRON):
        service = f"svc-b-{profile.value}"
        b = tiers[TrafficTier.B]
        specs.append(
            SeriesSpec(
                _series_key(service, "info"), TrafficTier.B, profile, b.median_per_bucket, b.cv, b.empty_bucket_rate
            )
        )

    for profile in (SeasonalProfile.FLAT, SeasonalProfile.DIURNAL):
        service = f"svc-c-{profile.value}"
        c = tiers[TrafficTier.C]
        specs.append(
            SeriesSpec(
                _series_key(service, "info"), TrafficTier.C, profile, c.median_per_bucket, c.cv, c.empty_bucket_rate
            )
        )

    for i, birth in enumerate(young_births):
        b = tiers[TrafficTier.B]
        profile = SeasonalProfile.FLAT if i % 2 == 0 else SeasonalProfile.DIURNAL
        specs.append(
            SeriesSpec(
                _series_key(f"svc-young-{i}", "info"),
                TrafficTier.B,
                profile,
                b.median_per_bucket,
                b.cv,
                b.empty_bucket_rate,
                birth_index=birth,
            )
        )

    for i in range(ephemeral_count):
        tier = TrafficTier.C if i % 2 == 0 else TrafficTier.D
        cal = tiers[tier]
        median_lifetime = calibration.EPHEMERAL_MEDIAN_LIFETIME_BUCKETS[tier]
        birth = int(rng.integers(0, max(1, grid_length - median_lifetime)))
        # Mostly hours-lived (the measured median), with a multi-day tail —
        # short pods are suppressed by the baseline min-history gate either
        # way; only the tail isolates the persistence gate's death-side effect.
        if rng.random() < 0.2:
            lifetime = int(rng.uniform(2, 6) * BUCKETS_PER_DAY)
        else:
            lifetime = max(2, int(rng.exponential(median_lifetime)))
        death = min(grid_length, birth + lifetime)
        specs.append(
            SeriesSpec(
                _series_key(f"pod-{i}", "info"),
                tier,
                SeasonalProfile.FLAT,
                cal.median_per_bucket,
                cal.cv,
                0.0,
                birth_index=birth,
                death_index=death,
            )
        )
    return specs


def inject_anomalies(
    scenario: Scenario,
    rng: np.random.Generator,
    eval_start: int,
    eval_end: int,
    spikes_per_series: int = 3,
    drops_per_series: int = 2,
    silences_per_series: int = 2,
) -> None:
    """Schedules non-overlapping anomalies on every persistent series inside
    the eval window and applies them to the counts."""
    plan = [
        (AnomalyKind.SPIKE, spikes_per_series, 6, 5.0),
        (AnomalyKind.DROP, drops_per_series, 12, 0.2),
        (AnomalyKind.SILENCE, silences_per_series, 12, 0.0),
    ]
    for spec in scenario.specs:
        if spec.is_ephemeral:
            continue
        occupied: list[tuple[int, int]] = []
        for kind, count, duration, factor in plan:
            for _ in range(count):
                for _attempt in range(50):
                    start = int(rng.integers(eval_start, eval_end - duration))
                    padded = (start - 2 * duration, start + 3 * duration)
                    if all(padded[1] <= s or padded[0] >= e for s, e in occupied):
                        occupied.append(padded)
                        anomaly = InjectedAnomaly(spec.key, kind, start, start + duration, factor)
                        scenario.anomalies.append(anomaly)
                        apply_anomaly(scenario.counts[spec.key], anomaly)
                        break


def build_scenario(
    grid: TimeGrid,
    grid_length: int,
    seed: int,
    ephemeral_count: int = 30,
    young_births: tuple[int, ...] = (),
) -> Scenario:
    rng = np.random.default_rng(seed)
    specs = build_population(grid_length, rng, ephemeral_count=ephemeral_count, young_births=young_births)
    counts = {spec.key: generate_counts(spec, grid, rng) for spec in specs}
    return Scenario(specs=specs, counts=counts)
