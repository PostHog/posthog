"""Hold a detector re-fire while the episode it belongs to is still decaying.

A detector scores the newest bucket against a long baseline, so the tail of a burst it
already fired on can score anomalous again hours later, even when that bucket is ordinary
next to the buckets around it. Every firing transition mints its own notification and its
own investigation, so one incident reaches the user more than once.

The hold is deliberately narrow. It applies only to a detector that scores against a
baseline, for an alert that is not firing now and that fired inside the decay window, and
it releases as soon as the newest bucket leaves the range of the buckets just before it. A
larger excursion, an excursion in the other direction, and an excursion after the window
all still fire. An alert that stays firing is untouched, so a sustained incident keeps its
current behavior.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

import structlog

from posthog.schema import AlertState, DetectorType, IntervalType

from posthog.interval_specs import interval_spec
from posthog.tasks.alerts.utils import AlertEvaluationResult

from products.alerts.backend.evaluation.contract import ComparableSeries, ExtractionResult
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration

logger = structlog.get_logger(__name__)

# The buckets before the newest one whose range it must leave to count as a new excursion
# rather than the tail of the last one.
EPISODE_DECAY_BUCKETS = 3


def hold_refire_within_episode_decay(
    alert: AlertConfiguration,
    extraction: ExtractionResult,
    evaluation: AlertEvaluationResult,
    now: datetime,
) -> AlertEvaluationResult:
    """Drop the breaches of a fire that only repeats an episode the alert already reported.

    The evaluation is returned unchanged in every other case, so the check still records the
    value, the scores and the triggered points of the bucket it scored.
    """
    if not evaluation.breaches:
        return evaluation
    if alert.state == AlertState.FIRING:
        return evaluation
    if _fires_on_a_fixed_bound(alert.detector_config or {}):
        return evaluation

    # The range test is arithmetic over values already in memory, so it runs before the
    # query that reads the alert's earlier checks.
    series = _scored_series(extraction, evaluation)
    if series is None or _leaves_recent_range(series):
        return evaluation
    if not _fired_within_decay_window(alert, extraction.interval_type, now):
        return evaluation

    logger.info(
        "alerts.detector_refire_held_within_episode_decay",
        alert_id=str(alert.id),
        value=evaluation.value,
    )
    return replace(evaluation, breaches=[])


def _fires_on_a_fixed_bound(detector_config: dict[str, Any]) -> bool:
    """True when the fire can come from a bound the user set rather than from a baseline.

    A threshold detector reads only ``lower_bound`` and ``upper_bound``, so a breach of it is a
    real bound crossing however ordinary the buckets around it look. An ensemble that holds a
    threshold member can fire on that member alone, and the evaluation does not record which
    member fired, so the hold releases for the whole ensemble.
    """
    if detector_config.get("type") == DetectorType.THRESHOLD.value:
        return True
    return any(_fires_on_a_fixed_bound(member) for member in detector_config.get("detectors") or [])


def _fired_within_decay_window(alert: AlertConfiguration, interval: IntervalType | None, now: datetime) -> bool:
    if interval is None:
        # A non-time-series result has no bucket to measure decay in.
        return False
    # One bucket of slack past the decay buckets, because the earlier fire can land anywhere
    # inside its own bucket and a scheduled check can run late.
    window = interval_spec(interval).period * (EPISODE_DECAY_BUCKETS + 1)
    return AlertCheck.objects.filter(
        alert_configuration=alert,
        state=AlertState.FIRING,
        created_at__gte=now - window,
    ).exists()


def _scored_series(extraction: ExtractionResult, evaluation: AlertEvaluationResult) -> ComparableSeries | None:
    """The series the breach was raised on. Breakdown evaluations name it by index."""
    index = (evaluation.triggered_metadata or {}).get("series_index", 0)
    return extraction.series[index] if index < len(extraction.series) else None


def _leaves_recent_range(series: ComparableSeries) -> bool:
    # The detector scores the last point of the series, so the hold reads the same one.
    values = [point.value for point in series.points if point.value is not None]
    if len(values) < 2:
        # Nothing to compare the newest bucket against, so leave the detector's call alone.
        return True
    current, recent = values[-1], values[-1 - EPISODE_DECAY_BUCKETS : -1]
    return not min(recent) <= current <= max(recent)
