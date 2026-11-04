from dataclasses import dataclass
from typing import Any

import numpy as np

from posthog.schema import DetectorType, IntervalType, TrendsQuery

from posthog.tasks.alerts.detectors.base import DetectionResult
from posthog.tasks.alerts.trends import TrendResult, _drop_incomplete_current_interval

# The AI judge (products.alerts.backend.judge) is not a registry detector, but its lookback
# is sized here like every other type, and the judge imports these so the two cannot drift.
LLM_DETECTOR_MIN_POINTS = 5

# How many points the AI judge sees for each insight interval: about a week of hours, a
# quarter of days, a year of weeks, two years of months. A series with no interval (a SQL
# alert) gets the daily size.
LLM_DETECTOR_DEFAULT_LOOKBACK = 90
LLM_DETECTOR_LOOKBACK_BY_INTERVAL: dict[str, int] = {
    IntervalType.MINUTE.value: 180,
    IntervalType.HOUR.value: 168,
    IntervalType.DAY.value: 90,
    IntervalType.WEEK.value: 52,
    IntervalType.MONTH.value: 24,
    IntervalType.QUARTER.value: 16,
    IntervalType.YEAR.value: 10,
}


def llm_detector_lookback(interval: str | None) -> int:
    """How many trailing points the AI judge is shown for a series at this interval."""
    if interval is None:
        return LLM_DETECTOR_DEFAULT_LOOKBACK
    return LLM_DETECTOR_LOOKBACK_BY_INTERVAL.get(interval, LLM_DETECTOR_DEFAULT_LOOKBACK)


# Minimum samples required for each detector type
DETECTOR_MIN_SAMPLES: dict[DetectorType, int] = {
    DetectorType.ZSCORE: 31,  # window + 1
    DetectorType.MAD: 31,  # window + 1
    DetectorType.THRESHOLD: 1,  # single data point sufficient
    DetectorType.IQR: 31,  # window + 1
    DetectorType.COPOD: 10,
    DetectorType.ECOD: 10,
    DetectorType.HBOS: 10,
    DetectorType.ISOLATION_FOREST: 10,
    DetectorType.KNN: 10,
    DetectorType.LOF: 20,  # needs n_neighbors samples
    DetectorType.OCSVM: 10,
    DetectorType.PCA: 10,
    DetectorType.LLM: LLM_DETECTOR_MIN_POINTS,
}

# Fallback window size used when no explicit window is set in the detector config
# (e.g. alerts saved before this field was introduced).
DETECTOR_DEFAULT_WINDOW = 30

# Maximum number of breakdown values to evaluate with a detector.
# Matches the default breakdown_limit in the query layer (25).
MAX_DETECTOR_BREAKDOWN_VALUES = 25


@dataclass
class PreparedSeries:
    """Data extracted from a TrendResult, ready for detection."""

    data: np.ndarray
    dates: list[str]
    label: str


def _prepare_series(series: TrendResult, is_non_time_series: bool, *, drop_current: bool) -> PreparedSeries | None:
    """Extract data + dates from a TrendResult and drop the incomplete interval.

    Returns None if the series has too few points for detection.
    """
    if is_non_time_series:
        data = np.array([series.get("aggregated_value", 0)])
    else:
        data = np.array(series.get("data", []))

    if len(data) == 0 or (not is_non_time_series and len(data) < 2):
        return None

    dates: list[str] = series.get("days") or series.get("labels") or []
    data, dates = _drop_incomplete_current_interval(data, dates, is_non_time_series, drop_current=drop_current)

    return PreparedSeries(data=data, dates=dates, label=series.get("label", "Series"))


def _extract_sub_detector_scores(detector_type_str: str, result: DetectionResult) -> list[dict[str, Any]] | None:
    """Extract per-sub-detector scores for ensemble detectors."""
    if detector_type_str != "ensemble" or not result.metadata:
        return None
    sub_results = result.metadata.get("sub_results", [])
    scores = [
        {"type": sr.get("type", "unknown"), "scores": sr.get("all_scores", [])}
        for sr in sub_results
        if sr.get("all_scores")
    ]
    return scores or None


def min_points_to_evaluate(detector_config: dict[str, Any]) -> int:
    """The fewest points a detector can score at all, as opposed to the window it prefers.

    The AI judge accepts its own minimum and simply sees a shorter table, so a series shorter
    than its window is still judged. A statistical detector needs its full training window.
    """
    if detector_config.get("type") == DetectorType.LLM.value:
        return DETECTOR_MIN_SAMPLES[DetectorType.LLM]
    return _compute_min_samples_for_detector(detector_config)


def _compute_min_samples_for_detector(detector_config: dict[str, Any], interval: str | None = None) -> int:
    """Compute the number of historical data points needed for a detector.

    Uses the configured ``window`` (falling back to a default) plus headroom
    for preprocessing (lags, diffs).  The result is floored by the
    per-detector ``DETECTOR_MIN_SAMPLES`` guard so we never train on fewer
    points than the algorithm requires. The AI detector has no window: its
    lookback follows the series ``interval``.
    """
    detector_type_str = detector_config.get("type", "zscore")

    if detector_type_str == "ensemble":
        sub_detectors = detector_config.get("detectors", [])
        return max(
            (_compute_min_samples_for_detector(d, interval) for d in sub_detectors),
            default=31,
        )

    detector_type = DetectorType(detector_type_str)
    guard = DETECTOR_MIN_SAMPLES.get(detector_type, 10)

    # Threshold detector doesn't need a training window
    if detector_type == DetectorType.THRESHOLD:
        return guard

    # The AI detector reads its lookback as it is: no training point is held back and no
    # preprocessing runs, so a series of exactly the lookback is enough.
    if detector_type == DetectorType.LLM:
        return max(llm_detector_lookback(interval), guard)

    window = detector_config.get("window") or DETECTOR_DEFAULT_WINDOW

    # Statistical detectors exclude training_offset_n trailing points from the fit (default 1);
    # a caller-configured larger offset needs the same headroom here as detect()/detect_batch()
    # apply, or every check silently falls short of _validate_data's minimum and never fires.
    offset = max(detector_config.get("training_offset_n") or 1, 1)

    # Account for preprocessing that consumes usable data points. diffs_n only ever runs a single
    # first-difference pass regardless of its configured magnitude (preprocess_data treats it as a
    # boolean), so only one synthetic leading point is ever introduced.
    preprocessing = detector_config.get("preprocessing") or {}
    lags_n = preprocessing.get("lags_n") or 0
    diffs_n = 1 if preprocessing.get("diffs_n") else 0

    samples_needed = window + offset + lags_n + diffs_n

    # Never go below the per-detector minimum guard
    return max(samples_needed, guard)


def _date_range_override_for_detector(query: TrendsQuery, min_samples: int) -> dict | None:
    """Calculate date range needed to get at least min_samples data points."""
    match query.interval:
        case IntervalType.DAY:
            date_from = f"-{min_samples}d"
        case IntervalType.WEEK:
            date_from = f"-{min_samples}w"
        case IntervalType.MONTH:
            date_from = f"-{min_samples}m"
        case IntervalType.QUARTER:
            date_from = f"-{min_samples}q"
        case IntervalType.YEAR:
            date_from = f"-{min_samples}y"
        case _:
            date_from = f"-{min_samples}h"

    return {"date_from": date_from}
