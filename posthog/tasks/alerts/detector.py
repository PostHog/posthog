from dataclasses import dataclass
from typing import Any, cast

import numpy as np

from posthog.schema import DetectorType, IntervalType, TrendsAlertConfig, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.models import AlertConfiguration, Insight
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.detectors import get_detector
from posthog.tasks.alerts.detectors.base import DetectionResult
from posthog.tasks.alerts.trends import (
    TrendResult,
    _drop_incomplete_current_interval,
    _has_breakdown,
    _is_non_time_series_trend,
    _pick_series_result,
)
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, AlertEvaluationResult
from posthog.utils import get_from_dict_or_attr

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


# ---------------------------------------------------------------------------
# Shared data-prep and detection helpers
# ---------------------------------------------------------------------------


@dataclass
class PreparedSeries:
    """Data extracted from a TrendResult, ready for detection."""

    data: np.ndarray
    dates: list[str]
    label: str


def _prepare_series(series: TrendResult, is_non_time_series: bool) -> PreparedSeries | None:
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
    data, dates = _drop_incomplete_current_interval(data, dates, is_non_time_series)

    return PreparedSeries(data=data, dates=dates, label=series.get("label", "Series"))


def _map_triggered_dates(result: DetectionResult, dates: list[str]) -> list[str]:
    """Map triggered indices to their corresponding date strings."""
    if not result.triggered_indices or not dates:
        return []
    return [dates[i] for i in result.triggered_indices if i < len(dates)]


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


# ---------------------------------------------------------------------------
# Min-samples and date-range helpers
# ---------------------------------------------------------------------------


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

    # Account for preprocessing that consumes usable data points
    preprocessing = detector_config.get("preprocessing") or {}
    lags_n = preprocessing.get("lags_n") or 0
    diffs_n = preprocessing.get("diffs_n") or 0

    samples_needed = window + 1 + lags_n + diffs_n

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
        case _:
            date_from = f"-{min_samples}h"

    return {"date_from": date_from}


# ---------------------------------------------------------------------------
# Alert check
# ---------------------------------------------------------------------------


def check_trends_alert_with_detector(
    alert: AlertConfiguration, insight: Insight, query: TrendsQuery, detector_config: dict[str, Any]
) -> AlertEvaluationResult:
    """Check a trends alert using detector-based anomaly detection."""
    config = (
        TrendsAlertConfig.model_validate(alert.config)
        if alert.config
        else TrendsAlertConfig(type="TrendsAlertConfig", series_index=0)
    )
    detector_type_str = detector_config.get("type", "zscore")

    # Request one extra sample because we drop the current (incomplete) interval.
    min_samples = _compute_min_samples_for_detector(detector_config) + 1
    filters_override = _date_range_override_for_detector(query, min_samples)

    is_non_time_series = _is_non_time_series_trend(query)
    if is_non_time_series:
        filters_override = None

    execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
    if query.interval == IntervalType.HOUR:
        execution_mode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS

    calculation_result = calculate_for_query_based_insight(
        insight,
        team=alert.team,
        execution_mode=execution_mode,
        user=None,
        filters_override=filters_override,
    )

    if calculation_result.result is None:
        raise RuntimeError(f"No results found for insight with alert id = {alert.id}")

    if not calculation_result.result:
        return AlertEvaluationResult(
            value=0,
            breaches=[],
            interval=query.interval.value if query.interval else None,
        )

    interval_value = query.interval.value if query.interval else None

    if _has_breakdown(query):
        breakdown_results = cast(list[TrendResult], calculation_result.result)[:MAX_DETECTOR_BREAKDOWN_VALUES]

        for bd_index, breakdown_result in enumerate(breakdown_results):
            prepared = _prepare_series(breakdown_result, is_non_time_series)
            if prepared is None:
                continue

            detector = get_detector(detector_config)
            result = detector.detect(prepared.data)

            if result.is_anomaly:
                current_value = float(prepared.data[-1])
                score_str = f" (anomaly probability: {result.score:.0%})" if result.score is not None else ""
                return AlertEvaluationResult(
                    value=current_value,
                    breaches=[
                        f"Anomaly detected in {prepared.label}: value {current_value:.2f}{score_str} using {detector_type_str} detector"
                    ],
                    anomaly_scores=result.all_scores or None,
                    triggered_points=result.triggered_indices if result.triggered_indices else None,
                    triggered_dates=_map_triggered_dates(result, prepared.dates) or None,
                    interval=interval_value,
                    triggered_metadata={"series_index": bd_index},
                )

        return AlertEvaluationResult(value=None, breaches=[], interval=interval_value)

    # Non-breakdown: pick a single series by index
    selected = _pick_series_result(config, calculation_result)
    prepared = _prepare_series(selected, is_non_time_series)
    if prepared is None:
        return AlertEvaluationResult(value=None, breaches=[], interval=interval_value)

    detector = get_detector(detector_config)
    result = detector.detect(prepared.data)

    triggered_dates = _map_triggered_dates(result, prepared.dates) or None

    breaches: list[str] = []
    if result.is_anomaly:
        current_value = float(prepared.data[-1])
        score_str = f" (anomaly probability: {result.score:.0%})" if result.score is not None else ""

        sub_scores_str = ""
        if detector_type_str == "ensemble" and result.metadata:
            sub_results = result.metadata.get("sub_results", [])
            if sub_results:
                parts = []
                for sr in sub_results:
                    sr_type = sr.get("type", "unknown")
                    sr_score = sr.get("score")
                    sr_fired = sr.get("is_anomaly", False)
                    score_pct = f"{sr_score:.0%}" if sr_score is not None else "n/a"
                    parts.append(f"{sr_type}: {score_pct}{' [fired]' if sr_fired else ''}")
                sub_scores_str = f" | sub-detectors: {', '.join(parts)}"

        breaches.append(
            f"Anomaly detected in {prepared.label}: value {current_value:.2f}{score_str} using {detector_type_str} detector{sub_scores_str}"
        )

    return AlertEvaluationResult(
        value=float(prepared.data[-1]) if len(prepared.data) > 0 else None,
        breaches=breaches if breaches else [],
        anomaly_scores=result.all_scores or None,
        triggered_points=result.triggered_indices if result.triggered_indices else None,
        triggered_dates=triggered_dates,
        interval=interval_value,
    )


# ---------------------------------------------------------------------------
# Simulation (read-only, no AlertCheck records)
# ---------------------------------------------------------------------------


def _build_series_sim_result(
    prepared: PreparedSeries,
    detector_config: dict[str, Any],
    detector_type_str: str,
) -> dict[str, Any]:
    """Run detect_batch on a single prepared series and return a simulation result dict."""
    detector = get_detector(detector_config)
    result = detector.detect_batch(prepared.data)

    triggered_dates = _map_triggered_dates(result, prepared.dates)
    scores = result.all_scores if result.all_scores else [None] * len(prepared.data)

    sim: dict[str, Any] = {
        "label": prepared.label,
        "data": prepared.data.tolist(),
        "dates": prepared.dates,
        "scores": scores,
        "triggered_indices": result.triggered_indices or [],
        "triggered_dates": triggered_dates,
        "total_points": len(prepared.data),
        "anomaly_count": len(result.triggered_indices) if result.triggered_indices else 0,
    }

    sub_scores = _extract_sub_detector_scores(detector_type_str, result)
    if sub_scores:
        sim["sub_detector_scores"] = sub_scores

    return sim


def simulate_detector_on_insight(
    insight: Insight,
    team: Any,
    detector_config: dict[str, Any],
    series_index: int = 0,
    date_from: str | None = None,
) -> dict[str, Any]:
    """Run a detector over historical insight data for chart visualization.

    No AlertCheck records are created — this is read-only.
    """
    if insight.query is None:
        raise ValueError("Insight has no valid query.")

    with upgrade_query(insight):
        query = insight.query

    kind = get_from_dict_or_attr(query, "kind")
    if kind in WRAPPER_NODE_KINDS:
        query = get_from_dict_or_attr(query, "source")
        kind = get_from_dict_or_attr(query, "kind")

    if kind != "TrendsQuery":
        raise ValueError("Only TrendsQuery insights are supported for simulation.")

    trends_query = TrendsQuery.model_validate(query)
    detector_type_str = detector_config.get("type", "zscore")
    min_samples = _compute_min_samples_for_detector(detector_config)

    # +1 because _drop_incomplete_current_interval removes the last point
    min_samples_with_padding = min_samples + 1
    min_date_from = _date_range_override_for_detector(trends_query, min_samples_with_padding)

    is_non_time_series = _is_non_time_series_trend(trends_query)
    if is_non_time_series:
        filters_override = None
    elif date_from:
        # Use whichever goes further back: the user's range or the detector minimum.
        # We parse both to absolute datetimes and pick the earlier one.
        from zoneinfo import ZoneInfo

        from posthog.utils import relative_date_parse

        utc = ZoneInfo("UTC")
        user_dt = relative_date_parse(date_from, utc)
        min_dt = relative_date_parse(min_date_from["date_from"], utc) if min_date_from else None
        if min_dt and min_dt < user_dt:
            filters_override = min_date_from
        else:
            filters_override = {"date_from": date_from}
    else:
        filters_override = min_date_from

    execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
    if trends_query.interval == IntervalType.HOUR:
        execution_mode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS

    calculation_result = calculate_for_query_based_insight(
        insight,
        team=team,
        execution_mode=execution_mode,
        user=None,
        filters_override=filters_override,
    )

    if calculation_result.result is None or not calculation_result.result:
        raise ValueError("No results found for insight.")

    interval_value = trends_query.interval.value if trends_query.interval else None

    if _has_breakdown(trends_query):
        all_results = cast(list[TrendResult], calculation_result.result)[:MAX_DETECTOR_BREAKDOWN_VALUES]
        breakdown_sims: list[dict[str, Any]] = []
        total_points = 0
        total_anomalies = 0

        for br in all_results:
            prepared = _prepare_series(br, is_non_time_series)
            if prepared is None:
                continue

            sim = _build_series_sim_result(prepared, detector_config, detector_type_str)
            breakdown_sims.append(sim)
            total_points += sim["total_points"]
            total_anomalies += sim["anomaly_count"]

        if not breakdown_sims:
            raise ValueError("No breakdown values had enough data points for simulation.")

        return {
            "data": [],
            "dates": [],
            "scores": [],
            "triggered_indices": [],
            "triggered_dates": [],
            "interval": interval_value,
            "total_points": total_points,
            "anomaly_count": total_anomalies,
            "breakdown_results": breakdown_sims,
        }

    # Non-breakdown
    config = TrendsAlertConfig(type="TrendsAlertConfig", series_index=series_index)
    selected = _pick_series_result(config, calculation_result)
    prepared = _prepare_series(selected, is_non_time_series)
    if prepared is None:
        raise ValueError("No data points found for the selected series.")

    sim = _build_series_sim_result(prepared, detector_config, detector_type_str)

    # For non-breakdown, promote fields to top level (no "label" key)
    sim.pop("label", None)
    return {**sim, "interval": interval_value}
