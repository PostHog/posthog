"""Runs the detector over a scenario and scores it against injected truth.

Everything here is deterministic given a seed. Bucket-level metrics are
grouped by the spec's tier and severity so the report can answer the ticket's
question directly: which band model holds the false-positive budget per tier
and per severity, and does error-severity overdispersion break Poisson.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace

import numpy as np

from products.apm.backend.logic.anomaly_detection.bands import BandModel
from products.apm.backend.logic.anomaly_detection.baseline import TimeGrid
from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.constants import BUCKETS_PER_DAY
from products.apm.backend.logic.anomaly_detection.detector import evaluate_series_bucket
from products.apm.backend.logic.anomaly_detection.issues import (
    IssueAction,
    IssueFingerprint,
    IssueSnapshot,
    evaluate_issue_transition,
    fingerprint_for,
    required_consecutive,
)
from products.apm.backend.logic.anomaly_detection.types import (
    VERDICT_DIRECTION,
    BaselineStage,
    BucketVerdict,
    SeriesHistory,
    TrafficTier,
    VerdictType,
)
from products.apm.backend.logic.anomaly_detection.validation.simulation import (
    AnomalyKind,
    NegativeBinomialNoise,
    Scenario,
    SeriesSpec,
)


@dataclass(slots=True)
class GroupMetrics:
    true_positive_buckets: int = 0
    false_positive_buckets: int = 0
    windows_total: int = 0
    windows_detected: int = 0
    series_count: int = 0

    @property
    def precision(self) -> float | None:
        flagged = self.true_positive_buckets + self.false_positive_buckets
        return self.true_positive_buckets / flagged if flagged else None

    @property
    def window_recall(self) -> float | None:
        return self.windows_detected / self.windows_total if self.windows_total else None


@dataclass(slots=True)
class IssueStats:
    opens_per_day: list[int] = field(default_factory=list)
    opens_in_truth: int = 0
    opens_total: int = 0

    @property
    def precision(self) -> float | None:
        return self.opens_in_truth / self.opens_total if self.opens_total else None

    @property
    def median_per_day(self) -> float:
        return float(np.median(self.opens_per_day)) if self.opens_per_day else 0.0

    @property
    def p95_per_day(self) -> float:
        return float(np.percentile(self.opens_per_day, 95)) if self.opens_per_day else 0.0


@dataclass(slots=True)
class ModelReport:
    model_name: str
    groups: dict[tuple[TrafficTier, str], GroupMetrics]
    stage_groups: dict[BaselineStage, GroupMetrics]
    issues: IssueStats
    silence_fp_ephemeral: int
    silence_fp_persistent: int
    silence_windows_detected: int
    silence_windows_total: int
    verdict_count: int
    eval_days: float
    scored_series: int

    @property
    def false_positives_per_series_day(self) -> float:
        fp = sum(g.false_positive_buckets for g in self.groups.values())
        denominator = self.scored_series * self.eval_days
        return fp / denominator if denominator else 0.0


def _verdict_matches_truth(scenario: Scenario, verdict: BucketVerdict) -> bool:
    truth = scenario.truth_at(verdict.key, verdict.bucket_index)
    return truth is not None and truth.direction is VERDICT_DIRECTION[verdict.verdict_type]


def run_model(
    scenario: Scenario,
    grid: TimeGrid,
    config: DetectionConfig,
    model: BandModel,
    eval_start: int,
    eval_end: int,
) -> ModelReport:
    specs_by_key = {spec.key: spec for spec in scenario.specs}
    shifted_keys = {a.key for a in scenario.anomalies if a.kind is AnomalyKind.LEVEL_SHIFT}
    histories = {
        spec.key: SeriesHistory(grid_start=grid.start, counts=scenario.counts[spec.key].copy())
        for spec in scenario.specs
    }

    groups: dict[tuple[TrafficTier, str], GroupMetrics] = defaultdict(GroupMetrics)
    stage_groups: dict[BaselineStage, GroupMetrics] = defaultdict(GroupMetrics)
    issues = IssueStats()
    snapshots: dict[IssueFingerprint, IssueSnapshot] = {}
    opens_by_day: dict[int, int] = defaultdict(int)
    silence_fp_ephemeral = 0
    silence_fp_persistent = 0
    verdict_count = 0
    detected_windows: set[int] = set()

    for index in range(eval_start, eval_end):
        tick_verdicts: dict[IssueFingerprint, BucketVerdict] = {}
        for spec in scenario.specs:
            history = histories[spec.key]
            verdict = evaluate_series_bucket(history, index, spec.key, grid, config, model)
            if verdict is None:
                continue
            history.excluded.add(index)
            verdict_count += 1

            if spec.key not in shifted_keys:
                matched = _verdict_matches_truth(scenario, verdict)
                group = groups[(spec.tier, spec.key.severity)]
                stage_group = stage_groups[verdict.stage]
                if matched:
                    group.true_positive_buckets += 1
                    stage_group.true_positive_buckets += 1
                else:
                    group.false_positive_buckets += 1
                    stage_group.false_positive_buckets += 1
                    if verdict.verdict_type is VerdictType.SILENCE:
                        if spec.is_ephemeral:
                            silence_fp_ephemeral += 1
                        else:
                            silence_fp_persistent += 1
                if matched:
                    for position, anomaly in enumerate(scenario.anomalies):
                        if anomaly.key == verdict.key and anomaly.contains(index):
                            detected_windows.add(position)

            fingerprint = fingerprint_for(verdict.key, verdict.verdict_type)
            existing = tick_verdicts.get(fingerprint)
            if existing is None or verdict.verdict_type is VerdictType.SILENCE:
                tick_verdicts[fingerprint] = verdict

        for fingerprint in set(snapshots) | set(tick_verdicts):
            verdict = tick_verdicts.get(fingerprint)
            if verdict is not None:
                required = required_consecutive(verdict.verdict_type, verdict.tier, config)
                outcome = evaluate_issue_transition(
                    snapshots.get(fingerprint), verdict.verdict_type, index, required, config
                )
            else:
                outcome = evaluate_issue_transition(
                    snapshots.get(fingerprint), None, index, config.open_after_buckets, config
                )
            if outcome.snapshot is None:
                snapshots.pop(fingerprint, None)
            else:
                snapshots[fingerprint] = outcome.snapshot
            if outcome.action in (IssueAction.OPEN, IssueAction.REOPEN):
                opens_by_day[(index - eval_start) // BUCKETS_PER_DAY] += 1
                issues.opens_total += 1
                if verdict is not None and _verdict_matches_truth(scenario, verdict):
                    issues.opens_in_truth += 1

    eval_days = (eval_end - eval_start) / BUCKETS_PER_DAY
    issues.opens_per_day = [opens_by_day.get(day, 0) for day in range(int(np.ceil(eval_days)))]

    silence_positions = [
        position
        for position, anomaly in enumerate(scenario.anomalies)
        if anomaly.kind is AnomalyKind.SILENCE and anomaly.key not in shifted_keys
    ]
    for position, anomaly in enumerate(scenario.anomalies):
        if anomaly.key in shifted_keys or anomaly.kind is AnomalyKind.LEVEL_SHIFT:
            continue
        spec = specs_by_key[anomaly.key]
        group = groups[(spec.tier, anomaly.key.severity)]
        group.windows_total += 1
        if position in detected_windows:
            group.windows_detected += 1

    scored_series = sum(1 for spec in scenario.specs if not spec.is_ephemeral and spec.key not in shifted_keys)
    return ModelReport(
        model_name=model.name,
        groups=dict(groups),
        stage_groups=dict(stage_groups),
        issues=issues,
        silence_fp_ephemeral=silence_fp_ephemeral,
        silence_fp_persistent=silence_fp_persistent,
        silence_windows_detected=sum(1 for p in silence_positions if p in detected_windows),
        silence_windows_total=len(silence_positions),
        verdict_count=verdict_count,
        eval_days=eval_days,
        scored_series=scored_series,
    )


def silence_gate_ablation(
    scenario: Scenario,
    grid: TimeGrid,
    config: DetectionConfig,
    model: BandModel,
    eval_start: int,
    eval_end: int,
) -> dict[str, ModelReport]:
    """The persistence-gate experiment on an identical scenario.

    Three rungs: the full design; the design minus the explicit persistence
    gate (its marginal effect over staged-baseline min-history, which already
    suppresses pods younger than the history requirement); and a naive config
    with neither, approximating the characterization's ungated 44% baseline.
    """
    gate_off = replace(
        config,
        persistence_window_buckets=0,
        persistence_recent_buckets=config.expiry_buckets,
    )
    naive = replace(
        gate_off,
        min_history_buckets=BUCKETS_PER_DAY // 24,  # an hour of life is enough to be scored
        min_baseline_samples=6,
        # Rate over the last hour, not the trailing day — a trailing-day floor
        # quietly does the persistence gate's work for short-lived pods.
        traffic_floor_window_buckets=BUCKETS_PER_DAY // 24,
    )
    return {
        "full design": run_model(scenario, grid, config, model, eval_start, eval_end),
        "no persistence gate": run_model(scenario, grid, gate_off, model, eval_start, eval_end),
        "naive (no gate, 1h history)": run_model(scenario, grid, naive, model, eval_start, eval_end),
    }


@dataclass(slots=True)
class RebaselineResult:
    buckets_to_quiet: int | None  # None: still firing at the end of the run
    verdicts_emitted: int

    @property
    def days_to_quiet(self) -> float | None:
        return self.buckets_to_quiet / BUCKETS_PER_DAY if self.buckets_to_quiet is not None else None


def rebaseline_experiment(
    spec: SeriesSpec,
    counts: np.ndarray,
    grid: TimeGrid,
    config: DetectionConfig,
    model: BandModel,
    shift_index: int,
    eval_end: int,
    stability_buckets: int | None = None,
) -> RebaselineResult:
    """How long a permanent level shift keeps firing.

    Passive mode (stability_buckets=None) relies on the exclusion cap
    readmitting new-level buckets. Stability mode models a caller-side policy:
    after N consecutive same-direction verdicts, treat the shift as the new
    level by re-anchoring the baseline window at the shift point — the series
    goes quiet immediately, at the cost of re-learning from scratch.
    """
    history = SeriesHistory(grid_start=grid.start, counts=counts.copy())
    quiet_run = 0
    consecutive_up = 0
    last_verdict_index: int | None = None
    verdicts_emitted = 0
    for index in range(shift_index, eval_end):
        verdict = evaluate_series_bucket(history, index, spec.key, grid, config, model)
        if verdict is not None:
            history.excluded.add(index)
            verdicts_emitted += 1
            last_verdict_index = index
            quiet_run = 0
            consecutive_up = consecutive_up + 1 if verdict.verdict_type is VerdictType.SPIKE else 0
            if stability_buckets is not None and consecutive_up >= stability_buckets:
                history.baseline_floor_index = index - stability_buckets
                history.excluded.clear()
                consecutive_up = 0
        else:
            quiet_run += 1
            consecutive_up = 0
        if quiet_run >= BUCKETS_PER_DAY:
            break
    if last_verdict_index is None:
        return RebaselineResult(buckets_to_quiet=0, verdicts_emitted=0)
    if quiet_run < BUCKETS_PER_DAY:
        return RebaselineResult(buckets_to_quiet=None, verdicts_emitted=verdicts_emitted)
    return RebaselineResult(buckets_to_quiet=last_verdict_index + 1 - shift_index, verdicts_emitted=verdicts_emitted)


@dataclass(slots=True)
class SweepCell:
    model_name: str
    lam: float
    cv: float
    false_positive_rate: float


def band_calibration_sweep(
    models: list[BandModel],
    alpha: float,
    seed: int,
    lambdas: tuple[float, ...] = (1.0, 10.0, 100.0, 1_000.0, 10_000.0),
    cvs: tuple[float, ...] = (0.12, 0.5, 2.2),
    n_samples: int = 40,
    trials: int = 500,
) -> list[SweepCell]:
    """Pure calibration check across the count range, no baseline machinery:
    baseline samples and the observed value are drawn from the same NB
    distribution, so a calibrated band flags ~2*alpha of clean observations.
    Covers the spec's lambda 1..10,000 range beyond what the population
    (tier medians up to ~1,590) exercises."""
    noise = NegativeBinomialNoise()
    cells = []
    for model in models:
        rng = np.random.default_rng(seed)
        for lam in lambdas:
            for cv in cvs:
                false_positives = 0
                for _ in range(trials):
                    draws = noise.sample(rng, np.full(n_samples + 1, lam), cv).astype(float)
                    samples, observed = draws[:-1], float(draws[-1])
                    band = model.compute(samples, observed, alpha)
                    if observed > band.upper or (observed < band.lower and observed > 0):
                        false_positives += 1
                cells.append(SweepCell(model.name, lam, cv, false_positives / trials))
    return cells
