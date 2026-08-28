"""The detector: (series history, grid, config, band model) -> verdicts.

Pure and stateless per bucket — the only cross-bucket state is the exclusion
set the caller threads through on ``SeriesHistory.excluded`` (buckets already
flagged anomalous, kept out of future baselines) and the issue layer's
snapshots. Consecutive-bucket confirmation lives in the issue layer, which has
the memory; this module answers "is this bucket outside its learned band".

Silence needs no separate expected-set machinery here: the dense grid makes a
missing rollup row a zero count, and the expiry gate stops zero-count verdicts
once a series has been quiet past the inactivity horizon.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from products.apm.backend.logic.anomaly_detection.bands import BandModel, widen
from products.apm.backend.logic.anomaly_detection.baseline import BaselineResult, TimeGrid, select_baseline
from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.types import (
    BaselineStage,
    BucketEvaluation,
    BucketVerdict,
    SeriesHistory,
    SeriesKey,
    TrafficTier,
    VerdictType,
)


def _trailing_rate(history: SeriesHistory, index: int, config: DetectionConfig) -> float:
    window_start = max(0, index - config.traffic_floor_window_buckets)
    window = history.counts[window_start:index]
    return float(np.mean(window)) if window.size else 0.0


def traffic_tier(history: SeriesHistory, index: int, config: DetectionConfig) -> TrafficTier:
    rate = _trailing_rate(history, index, config)
    if rate >= config.tier_a_min_per_bucket:
        return TrafficTier.A
    if rate >= config.tier_b_min_per_bucket:
        return TrafficTier.B
    if rate >= config.tier_c_min_per_bucket:
        return TrafficTier.C
    return TrafficTier.D


def _passes_gates(history: SeriesHistory, index: int, observed: float, config: DetectionConfig) -> bool:
    first_active = history.first_active_index
    if first_active is None:
        return False
    # Persistence, side one: alive since before the evaluation window.
    if index - first_active < config.persistence_window_buckets:
        return False
    if observed == 0:
        last_active = history.last_active_index(index)
        if last_active is None:
            return False
        # Expiry: a series quiet past the horizon has left silence coverage.
        if index - last_active > config.expiry_buckets:
            return False
        # Persistence, side two: recently alive (an ephemeral pod that died is
        # not a silent service — the characterization's decisive finding).
        if index - last_active > config.persistence_recent_buckets:
            return False
    # Sustained traffic floor over the trailing window.
    return _trailing_rate(history, index, config) >= config.traffic_floor_per_bucket


def _band_multiplier(key: SeriesKey, baseline: BaselineResult, config: DetectionConfig) -> float:
    factor = config.severity_variance_multipliers.get(key.severity, 1.0)
    if baseline.stage is BaselineStage.COLD_START:
        factor *= config.cold_start_band_multiplier
    if baseline.is_dst_shift_week:
        factor *= config.dst_band_multiplier
    return factor


def evaluate_series_bucket_detail(
    history: SeriesHistory,
    index: int,
    key: SeriesKey,
    grid: TimeGrid,
    config: DetectionConfig,
    band_model: BandModel,
) -> BucketEvaluation:
    observed = float(history.counts[index])
    if not _passes_gates(history, index, observed, config):
        return BucketEvaluation(observed=observed, band=None, stage=None, tier=None, verdict=None)

    baseline = select_baseline(history, index, grid, config)
    if not baseline.scorable:
        return BucketEvaluation(observed=observed, band=None, stage=baseline.stage, tier=None, verdict=None)

    band = band_model.compute(baseline.samples, observed, config.alpha_per_bucket)
    band = widen(band, _band_multiplier(key, baseline, config))
    tier = traffic_tier(history, index, config)

    verdict: BucketVerdict | None = None
    if observed == 0:
        # Zero observations are only ever silence — and only when the learned
        # seasonal expectation says logs were due (a near-zero overnight rate
        # cannot fire overnight silence).
        if band.expected >= config.silence_min_expected and tier is not TrafficTier.D:
            verdict = BucketVerdict(key, index, VerdictType.SILENCE, observed, band, baseline.stage, tier)
    elif observed > band.upper:
        verdict = BucketVerdict(key, index, VerdictType.SPIKE, observed, band, baseline.stage, tier)
    elif observed < band.lower:
        verdict = BucketVerdict(key, index, VerdictType.DROP, observed, band, baseline.stage, tier)
    return BucketEvaluation(observed=observed, band=band, stage=baseline.stage, tier=tier, verdict=verdict)


def evaluate_series_bucket(
    history: SeriesHistory,
    index: int,
    key: SeriesKey,
    grid: TimeGrid,
    config: DetectionConfig,
    band_model: BandModel,
) -> BucketVerdict | None:
    return evaluate_series_bucket_detail(history, index, key, grid, config, band_model).verdict


def evaluate_tick(
    series: Mapping[SeriesKey, SeriesHistory],
    index: int,
    grid: TimeGrid,
    config: DetectionConfig,
    band_model: BandModel,
) -> list[BucketVerdict]:
    verdicts = []
    for key, history in series.items():
        verdict = evaluate_series_bucket(history, index, key, grid, config, band_model)
        if verdict is not None:
            verdicts.append(verdict)
    return verdicts
