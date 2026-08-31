from dataclasses import dataclass
from typing import Any

import numpy as np

from posthog.schema import DetectorType, IntervalType, TrendsQuery

from posthog.tasks.alerts.detectors.base import DetectionResult
from posthog.tasks.alerts.trends import TrendResult, _drop_incomplete_current_interval

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
}

# Fallback window size used when no explicit window is set in the detector config
# (e.g. alerts saved before this field was introduced).
DETECTOR_DEFAULT_WINDOW = 30

# Maximum number of breakdown values to evaluate with a detector.
# Matches the default breakdown_limit in the query layer (25).
MAX_DETECTOR_BREAKDOWN_VALUES = 25

# Trailing complete intervals the detector skips before it scores a point.
# The just-closed interval is complete but still right-censored: late-arriving
# contributions keep filling it for a while after it closes, so it reads low and
# fires false anomalies. One interval of lag scores a point old enough to have
# settled. Set maturation_lag_n in detector_config to override (0 opts out for a
# metric that settles in real time).
DEFAULT_MATURATION_LAG = 1


def _resolve_maturation_lag(detector_config: dict[str, Any]) -> int:
    """Read maturation_lag_n from a detector config, falling back to the default."""
    raw = detector_config.get("maturation_lag_n")
    if raw is None:
        return DEFAULT_MATURATION_LAG
    return max(int(raw), 0)


@dataclass
class PreparedSeries:
    """Data extracted from a TrendResult, ready for detection."""

    data: np.ndarray
    dates: list[str]
    label: str


def _apply_maturation_lag(
    data: np.ndarray, dates: list[str], is_non_time_series: bool, maturation_lag: int
) -> tuple[np.ndarray, list[str]]:
    """Drop the freshest complete intervals so the scored point has settled.

    ``_drop_incomplete_current_interval`` removes only the in-progress interval,
    which leaves the just-closed interval — still right-censored — as the point
    the detector scores. Dropping ``maturation_lag`` more trailing intervals
    moves the scored point back to one old enough to have stopped changing. Keeps
    at least one point so a short series still reaches the detector's own guard.
    """
    if maturation_lag <= 0 or is_non_time_series:
        return data, dates
    n = min(maturation_lag, len(data) - 1)
    if n <= 0:
        return data, dates
    data = data[:-n]
    dates = dates[:-n] if dates else dates
    return data, dates


def _prepare_series(
    series: TrendResult, is_non_time_series: bool, *, drop_current: bool, maturation_lag: int = 0
) -> PreparedSeries | None:
    """Extract data + dates from a TrendResult and drop the incomplete interval.

    ``maturation_lag`` drops that many more trailing intervals so the detector
    scores a settled point rather than the just-closed one. Returns None if the
    series has too few points for detection.
    """
    if is_non_time_series:
        data = np.array([series.get("aggregated_value", 0)])
    else:
        data = np.array(series.get("data", []))

    if len(data) == 0 or (not is_non_time_series and len(data) < 2):
        return None

    dates: list[str] = series.get("days") or series.get("labels") or []
    data, dates = _drop_incomplete_current_interval(data, dates, is_non_time_series, drop_current=drop_current)
    data, dates = _apply_maturation_lag(data, dates, is_non_time_series, maturation_lag)

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


def _compute_min_samples_for_detector(detector_config: dict[str, Any]) -> int:
    """Compute the number of historical data points needed for a detector.

    Uses the configured ``window`` (falling back to a default) plus headroom
    for preprocessing (lags, diffs).  The result is floored by the
    per-detector ``DETECTOR_MIN_SAMPLES`` guard so we never train on fewer
    points than the algorithm requires.
    """
    detector_type_str = detector_config.get("type", "zscore")

    if detector_type_str == "ensemble":
        sub_detectors = detector_config.get("detectors", [])
        return max(
            (_compute_min_samples_for_detector(d) for d in sub_detectors),
            default=31,
        )

    detector_type = DetectorType(detector_type_str)
    guard = DETECTOR_MIN_SAMPLES.get(detector_type, 10)

    # Threshold detector doesn't need a training window
    if detector_type == DetectorType.THRESHOLD:
        return guard

    # Use the configured window, falling back to the default
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
