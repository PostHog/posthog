"""Noise-model calibration: representative defaults for production-shaped log traffic.

Values are modeled on an internal characterization of real log workloads and
deliberately rounded — absolute volumes here are representative, not
measurements. The raw characterization stays internal.

Representativeness caveat: the underlying workload is infrastructure logging.
Customer workloads may be smaller, spikier, less cron-shaped, and differently
ephemeral. The noise model is swappable (see simulation.NoiseModel) so a
design partner's measurements can replace this module wholesale.
"""

from __future__ import annotations

from dataclasses import dataclass

from products.apm.backend.logic.anomaly_detection.types import TrafficTier


@dataclass(frozen=True, slots=True)
class TierCalibration:
    median_per_bucket: float
    cv: float
    # Fraction of buckets naturally empty for persistent pairs at this tier.
    empty_bucket_rate: float


# 5-min bucket statistics per tier, persistent pairs (post-persistence-gate).
# Band C's natural empty rate collapses to ~0 once the persistence gate holds;
# band D stays too gappy for 5-min detection and sits below the floor.
TIER_CALIBRATION: dict[TrafficTier, TierCalibration] = {
    TrafficTier.A: TierCalibration(median_per_bucket=1_500.0, cv=0.12, empty_bucket_rate=0.0005),
    TrafficTier.B: TierCalibration(median_per_bucket=60.0, cv=0.35, empty_bucket_rate=0.002),
    TrafficTier.C: TierCalibration(median_per_bucket=20.0, cv=0.50, empty_bucket_rate=0.01),
    TrafficTier.D: TierCalibration(median_per_bucket=2.0, cv=0.80, empty_bucket_rate=0.29),
}

# Population share per tier: a small head of high-volume series and a long
# tail below the detection floor.
TIER_POPULATION_SHARE: dict[TrafficTier, float] = {
    TrafficTier.A: 0.15,
    TrafficTier.B: 0.05,
    TrafficTier.C: 0.12,
    TrafficTier.D: 0.68,
}

# Severity taxonomy is clean at ingest (canonical lowercase OTel values); info
# dominates, error is a sub-percent sliver.
SEVERITY_MIX: dict[str, float] = {"info": 0.85, "warn": 0.08, "debug": 0.065, "error": 0.005}

# Error streams run far more overdispersed (CV ~2) than info/debug at the same
# rate — the overdispersion headline the band bake-off exists to settle.
ERROR_CV = 2.2

# Seasonal peak/trough ratios: near-flat infra, diurnal user-facing traffic,
# cron step-functions firing at fixed local hours, and a weekend-peaking shape.
FLAT_PEAK_TROUGH = 1.07
DIURNAL_PEAK_TROUGH = 2.3
CRON_STEP_FACTOR = 14.0
CRON_STEP_HOURS = (3, 15)  # fixed local hours the step fires
WEEKEND_PEAK_FACTOR = 2.0

# Ephemeral pods dominate bands C and D: lifetimes of a couple of hours,
# mostly contiguous while alive — born, emit steadily, die.
EPHEMERAL_MEDIAN_LIFETIME_BUCKETS: dict[TrafficTier, int] = {TrafficTier.C: 24, TrafficTier.D: 12}
