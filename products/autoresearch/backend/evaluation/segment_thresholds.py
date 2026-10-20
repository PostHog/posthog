"""
The cut points between the Likely, Possible and Unlikely segments.

A pipeline's cut points follow lift over its realized base rate: Unlikely is below the base rate,
Likely is ``LIKELY_LIFT`` times the base rate or more, and Possible is in between. Until the checked
dates hold enough positives for a stable rate, the base rate of the champion's training population
applies, and a fixed pair applies when the champion has no recorded training counts. The online_performance
endpoint returns the current pair, and the frontend reads it from there, so the Predictions tab,
the Accuracy tab and online validation cannot disagree.
"""

from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from django.db import models

from posthog.dataclasses import frozen

from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun

LIKELY_LIFT = 3.0
FIXED_LIKELY_THRESHOLD = 0.6
FIXED_POSSIBLE_THRESHOLD = 0.2

# The base rate pools the newest checked dates, so it follows a drifting target.
BASE_RATE_DATES = 28
# A base rate from fewer positives than this is too noisy to set cut points from.
MIN_BASE_RATE_POSITIVES = 10
# A mean score this many times above or below the realized rate means the scores are not probabilities.
MISCALIBRATION_FACTOR = 2.0

# The unsampled training counts the champion fit records in AutoresearchModel.metrics.
TRAINING_POPULATION_KEY = "training_population"
TRAINING_POSITIVES_KEY = "training_positives"


class BaseRateSource(models.TextChoices):
    REALIZED = "realized"
    TRAINING = "training"
    FIXED = "fixed"


@frozen
class SegmentThresholds:
    likely: float
    possible: float
    # None when the fixed pair applies.
    base_rate: float | None
    # Checked dates the base rate pools.
    dates: int
    source: BaseRateSource


@frozen
class ScoreCalibration:
    """The champion's mean score against the realized rate, over the checked dates it emitted as champion."""

    mean_p_y: float
    base_rate: float

    @property
    def miscalibrated(self) -> bool:
        return not (1 / MISCALIBRATION_FACTOR <= self.mean_p_y / self.base_rate <= MISCALIBRATION_FACTOR)


def _significant(value: float, digits: int = 3) -> float:
    return float(f"{value:.{digits}g}")


def _champion_entries(runs: Iterable[AutoresearchRun]) -> Iterable[tuple[str, dict[str, Any]]]:
    """The emitted champion's metrics on each checked date. Shadow models score the same people, so they are skipped."""
    for run in runs:
        for model_id, metrics in (run.metrics.get("per_model") or {}).items():
            if metrics.get("emitted_role") == "champion":
                yield model_id, metrics
                break


def thresholds_for_base_rate(base_rate: float) -> SegmentThresholds:
    rate = _significant(base_rate)
    # The cap keeps Likely reachable when LIKELY_LIFT times a high base rate is near or above 100%.
    likely = min(LIKELY_LIFT * rate, rate + (1 - rate) / 2)
    return SegmentThresholds(
        likely=_significant(likely), possible=rate, base_rate=rate, dates=0, source=BaseRateSource.REALIZED
    )


def _stable_rate(positives: int, population: int) -> float | None:
    if positives < MIN_BASE_RATE_POSITIVES or positives >= population:
        return None
    return positives / population


def training_base_rate(model_metrics: dict[str, Any] | None) -> float | None:
    """
    The base rate of the population a model was fit on, from the counts before case-control sampling.

    The sampled rows overstate the rate by ``1 / negative_sample_rate``, so the fit records the
    unsampled counts. Null for a model fit before the counts were recorded.
    """
    metrics = model_metrics or {}
    return _stable_rate(int(metrics.get(TRAINING_POSITIVES_KEY) or 0), int(metrics.get(TRAINING_POPULATION_KEY) or 0))


def champion_training_base_rate(team_id: int, pipeline: AutoresearchPipeline) -> float | None:
    metrics = (
        AutoresearchModel.objects.for_team(team_id)
        .filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        .values_list("metrics", flat=True)
        .first()
    )
    return training_base_rate(metrics)


def segment_thresholds(runs: Iterable[AutoresearchRun], *, training_rate: float | None = None) -> SegmentThresholds:
    """
    The cut points from the realized base rate of the given completed validation runs. Until those
    runs hold enough positives, ``training_rate`` sets them, and the fixed pair applies without it.
    """
    scored = positives = dates = 0
    for _, metrics in _champion_entries(runs):
        scored += int(metrics.get("n_scored") or 0)
        positives += int(metrics.get("n_positive") or 0)
        dates += 1
    realized_rate = _stable_rate(positives, scored)
    if realized_rate is not None:
        return replace(thresholds_for_base_rate(realized_rate), dates=dates)
    if training_rate is not None:
        return replace(thresholds_for_base_rate(training_rate), dates=dates, source=BaseRateSource.TRAINING)
    return SegmentThresholds(
        likely=FIXED_LIKELY_THRESHOLD,
        possible=FIXED_POSSIBLE_THRESHOLD,
        base_rate=None,
        dates=dates,
        source=BaseRateSource.FIXED,
    )


def champion_score_calibration(runs: Iterable[AutoresearchRun], champion_id: str) -> ScoreCalibration | None:
    """
    Pooled mean score and realized rate of one champion. Null until its dates hold enough positives.

    Class weighting or resampling in train.py leaves scores that are not probabilities, and no
    correction at scoring time undoes it. Cut points from the base rate do not mean "N times as
    likely" for such a model, so the UI warns about it.
    """
    scored = positives = 0
    predicted = 0.0
    for model_id, metrics in _champion_entries(runs):
        mean_p_y = metrics.get("mean_p_y")
        if model_id != champion_id or mean_p_y is None:
            continue
        n = int(metrics.get("n_scored") or 0)
        scored += n
        positives += int(metrics.get("n_positive") or 0)
        predicted += float(mean_p_y) * n
    if positives < MIN_BASE_RATE_POSITIVES or scored == 0:
        return None
    return ScoreCalibration(mean_p_y=round(predicted / scored, 4), base_rate=round(positives / scored, 4))
