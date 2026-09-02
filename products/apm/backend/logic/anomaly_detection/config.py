"""Detection dials. Every value here is an alpha parameter expected to move.

Defaults are calibrated against an internal characterization of production
log workloads — a calibrating floor, not a universal. That is why each dial is env-tunable (``APM_ANOMALY_*``)
rather than a constant: argocd can retune without a deploy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields

from products.apm.backend.logic.anomaly_detection.constants import BUCKETS_PER_DAY, BUCKETS_PER_HOUR, BUCKETS_PER_WEEK
from products.apm.backend.logic.anomaly_detection.types import TrafficTier

_ENV_PREFIX = "APM_ANOMALY_"


@dataclass(frozen=True, slots=True)
class DetectionConfig:
    # --- band significance ---
    # Per-side false-flag budget per series per day; alpha per bucket is this / 288.
    false_flag_budget_per_day: float = 0.05
    # Widening for band models that assume their dispersion (e.g. Poisson).
    # Empty by default: the recommended negative-binomial model measures
    # dispersion from the samples, so widening would double-count it — see
    # validation/REPORT.md.
    severity_variance_multipliers: dict[str, float] = field(default_factory=dict)
    # Minimum variance-to-mean ratio used when estimating dispersion, so a
    # MAD-zero / flat baseline can't produce a zero-width band.
    dispersion_floor: float = 1.0
    # Rate floor for count bands: a near-zero learned rate still gets a small
    # nonzero band, so the first log after a quiet hour is not a spike.
    band_rate_floor: float = 1.0
    # Bands widen by this factor during DST shift weeks (reduced confidence).
    dst_band_multiplier: float = 1.5
    # Bands widen by this factor while a series is in cold start.
    cold_start_band_multiplier: float = 2.0

    # --- baseline stages (thresholds in buckets of series age) ---
    min_history_buckets: int = 3 * BUCKETS_PER_DAY
    cold_start_until_buckets: int = 14 * BUCKETS_PER_DAY
    developing_until_buckets: int = 6 * BUCKETS_PER_WEEK
    # Pooling half-width around the scored time-of-week slot, in buckets.
    developing_pool_buckets: int = 12  # ±60 min
    mature_pool_buckets: int = 2  # ±10 min
    max_lookback_buckets: int = 12 * BUCKETS_PER_WEEK
    # Baselines only use buckets at least this old. Without a guard, the
    # trailing edge of the pool overlaps an ongoing anomaly, which inflates the
    # dispersion estimate until the detector legitimizes the incident it should
    # be flagging.
    baseline_guard_buckets: int = BUCKETS_PER_DAY
    min_baseline_samples: int = 12
    # Anomalous buckets are excluded from baselines, but only up to this share
    # of the candidate window — beyond it a level shift re-baselines itself.
    exclusion_cap_fraction: float = 0.5

    # --- level component ---
    level_adjustment_enabled: bool = True
    level_window_buckets: int = BUCKETS_PER_DAY
    level_factor_clamp: float = 2.0

    # --- gates ---
    # Sustained traffic floor: >=1 log/min over the floor window (per-bucket mean).
    traffic_floor_per_bucket: float = 5.0
    traffic_floor_window_buckets: int = BUCKETS_PER_DAY
    # Persistence: the series must have been alive on both sides of the window
    # (the characterization's decisive gate: silence FP 44% -> 11.75%).
    persistence_window_buckets: int = BUCKETS_PER_DAY
    persistence_recent_buckets: int = 2 * BUCKETS_PER_HOUR
    # A series absent longer than this expires out of silence coverage.
    expiry_buckets: int = 1 * BUCKETS_PER_DAY

    # --- tiers (per-bucket rate edges: 0.5/s, 0.1/s, 1/min) ---
    tier_a_min_per_bucket: float = 150.0
    tier_b_min_per_bucket: float = 30.0
    tier_c_min_per_bucket: float = 5.0

    # --- silence ---
    # Seasonal gate: expected count in the bucket must reach this for silence
    # to be a candidate (a near-zero overnight rate cannot fire overnight).
    silence_min_expected: float = 5.0
    # Consecutive empty buckets required before a silence issue opens, per tier.
    silence_confirm_buckets: dict[TrafficTier, int] = field(
        default_factory=lambda: {TrafficTier.A: 1, TrafficTier.B: 2, TrafficTier.C: 3}
    )

    # --- issue lifecycle ---
    # Consecutive anomalous buckets before a spike/drop issue opens.
    open_after_buckets: int = 2
    # Consecutive normal buckets before an active issue resolves.
    resolve_after_buckets: int = 12
    # A recurrence within this window reopens the resolved issue; later ones are new.
    reopen_window_buckets: int = 7 * BUCKETS_PER_DAY

    def __post_init__(self) -> None:
        if not (0.0 <= self.exclusion_cap_fraction <= 1.0):
            raise ValueError(
                f"DetectionConfig exclusion_cap_fraction must be between 0 and 1, got {self.exclusion_cap_fraction}"
            )

    @property
    def alpha_per_bucket(self) -> float:
        return self.false_flag_budget_per_day / BUCKETS_PER_DAY

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> DetectionConfig:
        """Scalar dials only — the dict-valued dials (severity multipliers,
        silence confirmation) need code changes, which is deliberate: their
        shape is part of the detection contract, not a tuning knob."""
        env = os.environ if environ is None else environ
        overrides: dict[str, object] = {}
        for f in fields(cls):
            raw = env.get(f"{_ENV_PREFIX}{f.name.upper()}")
            if raw is None:
                continue
            if f.type in ("int",):
                overrides[f.name] = int(raw)
            elif f.type in ("float",):
                overrides[f.name] = float(raw)
            elif f.type in ("bool",):
                overrides[f.name] = raw.strip().lower() in ("1", "true", "yes")
        return cls(**overrides)  # type: ignore[arg-type]
