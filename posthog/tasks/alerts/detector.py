from typing import Any, cast

import numpy as np

from posthog.schema import DetectorType, IntervalType, TrendsAlertConfig, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.models import AlertConfiguration, Insight
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.detectors import get_detector
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


def check_trends_alert_with_detector(
    alert: AlertConfiguration, insight: Insight, query: TrendsQuery, detector_config: dict[str, Any]
) -> AlertEvaluationResult:
    """
    Check a trends alert using detector-based anomaly detection.

    Args:
        alert: The alert configuration
        insight: The insight to check
        query: The trends query
        detector_config: Detector configuration dict

    Returns:
        AlertEvaluationResult with anomaly detection results
    """
    config = (
        TrendsAlertConfig.model_validate(alert.config)
        if alert.config
        else TrendsAlertConfig(type="TrendsAlertConfig", series_index=0)
    )
    detector_type_str = detector_config.get("type", "zscore")

    # Calculate date range to fetch enough historical data for this detector.
    # Request one extra sample because the query always includes the current
    # (incomplete) interval which we drop below to avoid false positives.
    min_samples = _compute_min_samples_for_detector(detector_config) + 1
    filters_override = _date_range_override_for_detector(query, min_samples)

    is_non_time_series = _is_non_time_series_trend(query)
    if is_non_time_series:
        filters_override = None  # full insight for aggregated values

    # Use cache for daily+, but not for hourly
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

    has_breakdown = _has_breakdown(query)

    interval_value = query.interval.value if query.interval else None

    if has_breakdown:
        # For breakdowns, evaluate each breakdown value independently and fire on the first anomaly
        breakdown_results = cast(list[TrendResult], calculation_result.result)[:MAX_DETECTOR_BREAKDOWN_VALUES]

        for bd_index, breakdown_result in enumerate(breakdown_results):
            if is_non_time_series:
                data = np.array([breakdown_result.get("aggregated_value", 0)])
            else:
                data = np.array(breakdown_result.get("data", []))

            if len(data) == 0 or (not is_non_time_series and len(data) < 2):
                continue

            dates: list[str] = breakdown_result.get("days") or breakdown_result.get("labels") or []
            data, dates = _drop_incomplete_current_interval(data, dates, is_non_time_series)

            detector = get_detector(detector_config)
            result = detector.detect(data)

            if result.is_anomaly:
                label = breakdown_result.get("label", "Series")
                current_value = float(data[-1])
                score_str = f" (anomaly probability: {result.score:.0%})" if result.score is not None else ""
                triggered_dates: list[str] | None = None
                if result.triggered_indices and dates:
                    triggered_dates = [dates[i] for i in result.triggered_indices if i < len(dates)]

                return AlertEvaluationResult(
                    value=current_value,
                    breaches=[
                        f"Anomaly detected in {label}: value {current_value:.2f}{score_str} using {detector_type_str} detector"
                    ],
                    anomaly_scores=result.all_scores or None,
                    triggered_points=result.triggered_indices if result.triggered_indices else None,
                    triggered_dates=triggered_dates,
                    interval=interval_value,
                    triggered_metadata={"series_index": bd_index},
                )

        # No anomaly in any breakdown value
        return AlertEvaluationResult(value=None, breaches=[], interval=interval_value)

    # Non-breakdown: pick a single series by index
    selected_series_result = _pick_series_result(config, calculation_result)

    # Extract time series data
    if is_non_time_series:
        data = np.array([selected_series_result.get("aggregated_value", 0)])
    else:
        data = np.array(selected_series_result.get("data", []))

    if len(data) == 0:
        return AlertEvaluationResult(value=None, breaches=[], interval=interval_value)

    # Extract dates for chart alignment
    dates = selected_series_result.get("days") or selected_series_result.get("labels") or []

    data, dates = _drop_incomplete_current_interval(data, dates, is_non_time_series)

    # Create and run detector
    detector = get_detector(detector_config)
    result = detector.detect(data)

    # Map triggered indices to their corresponding dates
    triggered_dates = None
    if result.triggered_indices and dates:
        triggered_dates = [dates[i] for i in result.triggered_indices if i < len(dates)]

    # Build breaches message if anomaly detected
    breaches: list[str] = []
    if result.is_anomaly:
        label = selected_series_result.get("label", "Series")
        current_value = float(data[-1])
        score_str = f" (anomaly probability: {result.score:.0%})" if result.score is not None else ""

        # For ensemble detectors, include per-sub-detector scores
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
            f"Anomaly detected in {label}: value {current_value:.2f}{score_str} using {detector_type_str} detector{sub_scores_str}"
        )

    return AlertEvaluationResult(
        value=float(data[-1]) if len(data) > 0 else None,
        breaches=breaches if breaches else [],
        anomaly_scores=result.all_scores or None,
        triggered_points=result.triggered_indices if result.triggered_indices else None,
        triggered_dates=triggered_dates,
        interval=interval_value,
    )


def simulate_detector_on_insight(
    insight: Insight,
    team: Any,
    detector_config: dict[str, Any],
    series_index: int = 0,
    date_from: str | None = None,
) -> dict[str, Any]:
    """
    Run a detector over the full historical data of an insight using detect_batch().
    Returns per-point scores and triggered indices for chart visualization.
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

    # Calculate minimum samples needed (same logic as the actual alert check)
    min_samples = _compute_min_samples_for_detector(detector_config)

    # Fetch enough historical data
    is_non_time_series = _is_non_time_series_trend(trends_query)
    if is_non_time_series:
        filters_override = None
    elif date_from:
        # User-requested range — use it directly, but the detector will still
        # need min_samples internally so we don't clamp here; if the user asks
        # for too few points the detector simply won't trigger on early ones.
        filters_override = {"date_from": date_from}
    else:
        filters_override = _date_range_override_for_detector(trends_query, min_samples)

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

    has_breakdown = _has_breakdown(trends_query)
    interval_value = trends_query.interval.value if trends_query.interval else None

    if has_breakdown:
        # Simulate each breakdown value independently (up to the cap)
        all_breakdown_results = cast(list[TrendResult], calculation_result.result)[:MAX_DETECTOR_BREAKDOWN_VALUES]
        breakdown_sim_results: list[dict[str, Any]] = []
        total_points = 0
        total_anomalies = 0

        for br in all_breakdown_results:
            label = br.get("label", "Series")
            if is_non_time_series:
                bd_data_list: list[float] = [float(br.get("aggregated_value", 0))]
            else:
                bd_data_list = [float(v) for v in br.get("data", [])]

            bd_data = np.array(bd_data_list)
            if len(bd_data) == 0 or (not is_non_time_series and len(bd_data) < 2):
                continue

            bd_dates: list[str] = br.get("days") or br.get("labels") or []
            bd_data, bd_dates = _drop_incomplete_current_interval(bd_data, bd_dates, is_non_time_series)

            detector = get_detector(detector_config)
            bd_result = detector.detect_batch(bd_data)

            bd_triggered_dates: list[str] = []
            if bd_result.triggered_indices and bd_dates:
                bd_triggered_dates = [bd_dates[i] for i in bd_result.triggered_indices if i < len(bd_dates)]

            bd_scores = bd_result.all_scores if bd_result.all_scores else [None] * len(bd_data)
            bd_anomaly_count = len(bd_result.triggered_indices) if bd_result.triggered_indices else 0

            total_points += len(bd_data)
            total_anomalies += bd_anomaly_count

            bd_sim: dict[str, Any] = {
                "label": label,
                "data": bd_data_list,
                "dates": bd_dates,
                "scores": bd_scores,
                "triggered_indices": bd_result.triggered_indices or [],
                "triggered_dates": bd_triggered_dates,
                "total_points": len(bd_data),
                "anomaly_count": bd_anomaly_count,
            }

            # Include sub-detector scores for ensemble detectors
            if detector_type_str == "ensemble" and bd_result.metadata:
                sub_results = bd_result.metadata.get("sub_results", [])
                bd_sim["sub_detector_scores"] = [
                    {"type": sr.get("type", "unknown"), "scores": sr.get("all_scores", [])}
                    for sr in sub_results
                    if sr.get("all_scores")
                ]

            breakdown_sim_results.append(bd_sim)

        if not breakdown_sim_results:
            raise ValueError("No breakdown values had enough data points for simulation.")

        # Top-level fields use empty arrays for data/scores/triggered — the real
        # per-breakdown data lives in breakdown_results. total_points and
        # anomaly_count are aggregated across all breakdowns.
        return {
            "data": [],
            "dates": [],
            "scores": [],
            "triggered_indices": [],
            "triggered_dates": [],
            "interval": interval_value,
            "total_points": total_points,
            "anomaly_count": total_anomalies,
            "breakdown_results": breakdown_sim_results,
        }

    # Non-breakdown: pick a single series by index
    config = TrendsAlertConfig(type="TrendsAlertConfig", series_index=series_index)
    selected_series_result = _pick_series_result(config, calculation_result)

    if is_non_time_series:
        data_list: list[float] = [float(selected_series_result.get("aggregated_value", 0))]
    else:
        data_list = [float(v) for v in selected_series_result.get("data", [])]

    data = np.array(data_list)
    if len(data) == 0:
        raise ValueError("No data points found for the selected series.")

    dates: list[str] = selected_series_result.get("days") or selected_series_result.get("labels") or []

    # Run batch detection
    detector = get_detector(detector_config)
    result = detector.detect_batch(data)

    # Map triggered indices to dates
    triggered_dates: list[str] = []
    if result.triggered_indices and dates:
        triggered_dates = [dates[i] for i in result.triggered_indices if i < len(dates)]

    scores = result.all_scores if result.all_scores else [None] * len(data)

    # For ensemble detectors, include per-sub-detector scores for visualization
    sub_detector_scores: list[dict[str, Any]] | None = None
    if detector_type_str == "ensemble" and result.metadata:
        sub_results = result.metadata.get("sub_results", [])
        sub_detector_scores = [
            {"type": sr.get("type", "unknown"), "scores": sr.get("all_scores", [])}
            for sr in sub_results
            if sr.get("all_scores")
        ]

    response: dict[str, Any] = {
        "data": data_list,
        "dates": dates,
        "scores": scores,
        "triggered_indices": result.triggered_indices or [],
        "triggered_dates": triggered_dates,
        "interval": interval_value,
        "total_points": len(data),
        "anomaly_count": len(result.triggered_indices) if result.triggered_indices else 0,
    }
    if sub_detector_scores:
        response["sub_detector_scores"] = sub_detector_scores

    return response
