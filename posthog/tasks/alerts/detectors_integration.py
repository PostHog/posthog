"""
Integration layer between the detector system and existing alerts infrastructure.

This module bridges the new detector abstraction with PostHog's existing alert evaluation system,
allowing both legacy threshold-based alerts and new detector-based alerts to coexist.
"""

import structlog

from posthog.schema import DetectorConfig, TrendsQuery

from posthog.alerts.detectors import create_detector
from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.models import AlertConfiguration, Insight
from posthog.tasks.alerts.utils import AlertEvaluationResult

logger = structlog.get_logger(__name__)


def check_trends_alert_with_detectors(
    alert: AlertConfiguration, insight: Insight, query: TrendsQuery
) -> AlertEvaluationResult:
    """
    Enhanced alert checking that supports both legacy thresholds and new detectors.

    If the alert has detector_config, use the detector system.
    Otherwise, fall back to existing threshold-based logic.
    """

    # Check if alert has detector configuration
    if alert.detector_config:
        try:
            detector_config = DetectorConfig.model_validate(alert.detector_config)
            return _run_detector_evaluation(alert, insight, query, detector_config)
        except Exception as e:
            logger.warning(
                "Failed to run detector evaluation, falling back to threshold", alert_id=alert.id, error=str(e)
            )

    # Fall back to existing threshold logic
    from posthog.tasks.alerts.trends import check_trends_alert

    return check_trends_alert(alert, insight, query)


def _run_detector_evaluation(
    alert: AlertConfiguration, insight: Insight, query: TrendsQuery, detector_config: DetectorConfig
) -> AlertEvaluationResult:
    """Run detection using the configured detector."""

    # Create detector instance
    detector = create_detector(detector_config.type, detector_config.config.model_dump())

    # Get time series data from insight
    time_series_values = _extract_time_series_from_insight(alert, insight, query)

    if not time_series_values:
        logger.warning("No time series data found for detector evaluation", alert_id=alert.id)
        return AlertEvaluationResult(value=None, breaches=[])

    # Run detection
    series_name = _get_series_name_from_insight(insight, query)
    detection_result = detector.detect(
        values=time_series_values, series_name=series_name, value_type=detector_config.value_type
    )

    # Convert DetectionResult to AlertEvaluationResult
    breaches = detection_result.breach_messages if detection_result.is_breach else []

    # Store the full detection result in the AlertEvaluationResult
    detector_result_dict = {
        "value": detection_result.value,
        "detector_score": detection_result.detector_score,
        "is_breach": detection_result.is_breach,
        "breach_messages": detection_result.breach_messages,
        "metadata": detection_result.metadata,
    }

    return AlertEvaluationResult(value=detection_result.value, breaches=breaches, detector_result=detector_result_dict)


def _extract_time_series_from_insight(alert: AlertConfiguration, insight: Insight, query: TrendsQuery) -> list[float]:
    """
    Extract time series values from insight calculation result.

    This mimics the logic from trends.py but extracts a full time series
    instead of just current/previous values.
    """

    # Calculate insight for a longer time window to get historical data
    # Use last 120 days to ensure we have enough data for statistical detectors
    filters_override = {"date_from": "-120d"}

    try:
        calculation_result = calculate_for_query_based_insight(
            insight,
            team=alert.team,
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            user=None,
            filters_override=filters_override,
        )

        if not calculation_result.result:
            logger.warning("No calculation result for insight", alert_id=alert.id)
            return []

        # Handle breakdown vs non-breakdown results
        results = calculation_result.result
        if not isinstance(results, list):
            return []

        # For now, take the first series (later we can handle breakdowns)
        if len(results) > 0:
            first_series = results[0]

            # Extract data array from the series
            if "data" in first_series and isinstance(first_series["data"], list):
                # Filter out None values and convert to float
                values = []
                for val in first_series["data"]:
                    if val is not None:
                        try:
                            values.append(float(val))
                        except (ValueError, TypeError):
                            continue
                return values

            # Handle aggregated value case (non-time series)
            elif "aggregated_value" in first_series and first_series["aggregated_value"] is not None:
                try:
                    return [float(first_series["aggregated_value"])]
                except (ValueError, TypeError):
                    pass

        return []

    except Exception as e:
        logger.error("Failed to extract time series from insight", alert_id=alert.id, error=str(e), exc_info=True)
        return []


def _get_series_name_from_insight(insight: Insight, query: TrendsQuery) -> str:
    """Get a descriptive name for the series being monitored."""

    if insight.name:
        return insight.name

    # Try to extract from query
    if hasattr(query, "series") and query.series and len(query.series) > 0:
        first_series = query.series[0]
        if hasattr(first_series, "name") and first_series.name:
            return first_series.name

    return "Series"


# Thread-local storage functions removed - now passing detector results directly via AlertEvaluationResult
