from typing import Union

from posthog.schema import (
    AlertDetectorsConfig,
    DetectorGroup,
    DetectorType,
    FilterLogicalOperator,
    KMeansDetectorConfig,
    ThresholdDetectorConfig,
    ZScoreDetectorConfig,
)
from posthog.tasks.alerts.detectors.base import BaseDetector, DetectorResult
from posthog.tasks.alerts.detectors.kmeans import KMeansDetector
from posthog.tasks.alerts.detectors.threshold import ThresholdDetector
from posthog.tasks.alerts.detectors.zscore import ZScoreDetector


DetectorConfigType = Union[ThresholdDetectorConfig, ZScoreDetectorConfig, KMeansDetectorConfig]


def create_detector(config: DetectorConfigType) -> BaseDetector:
    """Factory function to create a detector instance from its configuration."""
    match config.type:
        case DetectorType.THRESHOLD | "threshold":
            if not isinstance(config, ThresholdDetectorConfig):
                raise ValueError(f"Expected ThresholdDetectorConfig, got {type(config)}")
            return ThresholdDetector(config)
        case DetectorType.ZSCORE | "zscore":
            if not isinstance(config, ZScoreDetectorConfig):
                raise ValueError(f"Expected ZScoreDetectorConfig, got {type(config)}")
            return ZScoreDetector(config)
        case DetectorType.KMEANS | "kmeans":
            if not isinstance(config, KMeansDetectorConfig):
                raise ValueError(f"Expected KMeansDetectorConfig, got {type(config)}")
            return KMeansDetector(config)
        case _:
            raise ValueError(f"Unknown detector type: {config.type}")


def _evaluate_detector_or_group(
    detector_or_group: Union[DetectorConfigType, DetectorGroup],
    data: list[float],
    timestamps: list[str],
    series_label: str,
    check_index: int | None = None,
) -> DetectorResult:
    """
    Recursively evaluate a detector config or detector group.

    For single detectors: create and evaluate the detector.
    For groups: evaluate all children and combine with AND/OR logic.
    """
    # Check if this is a group (has 'detectors' attribute)
    if isinstance(detector_or_group, DetectorGroup):
        return _evaluate_group(detector_or_group, data, timestamps, series_label, check_index)

    # It's a single detector config
    detector = create_detector(detector_or_group)
    return detector.evaluate(data, timestamps, series_label, check_index)


def _evaluate_group(
    group: DetectorGroup,
    data: list[float],
    timestamps: list[str],
    series_label: str,
    check_index: int | None = None,
) -> DetectorResult:
    """
    Evaluate a detector group with AND/OR logic.

    AND: All detectors must be breaching for the group to breach
    OR: Any detector breaching means the group breaches
    """
    if not group.detectors:
        return DetectorResult(
            is_breaching=False,
            breach_indices=[],
            value=None,
            message="Empty detector group",
        )

    results = []
    for detector_or_nested_group in group.detectors:
        result = _evaluate_detector_or_group(detector_or_nested_group, data, timestamps, series_label, check_index)
        results.append(result)

    # Combine results based on logical operator
    is_and = group.type == FilterLogicalOperator.AND_ or group.type == "AND"

    if is_and:
        # AND: All must be breaching
        is_breaching = all(r.is_breaching for r in results)

        if is_breaching:
            # Intersection of breach indices
            all_breach_sets = [set(r.breach_indices) for r in results if r.breach_indices]
            if all_breach_sets:
                breach_indices = list(set.intersection(*all_breach_sets))
            else:
                breach_indices = []

            messages = [r.message for r in results if r.message]
            return DetectorResult(
                is_breaching=True,
                breach_indices=sorted(breach_indices),
                value=None,
                message=" AND ".join(messages) if messages else "All detectors triggered",
            )
        else:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message=None,
            )
    else:
        # OR: Any can be breaching
        is_breaching = any(r.is_breaching for r in results)

        if is_breaching:
            # Union of breach indices
            breach_indices = []
            for r in results:
                if r.is_breaching:
                    breach_indices.extend(r.breach_indices)
            breach_indices = sorted(set(breach_indices))

            messages = [r.message for r in results if r.is_breaching and r.message]
            return DetectorResult(
                is_breaching=True,
                breach_indices=breach_indices,
                value=None,
                message=" OR ".join(messages) if messages else "At least one detector triggered",
            )
        else:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message=None,
            )


def evaluate_detectors(
    config: AlertDetectorsConfig,
    data: list[float],
    timestamps: list[str],
    series_label: str,
    check_index: int | None = None,
) -> DetectorResult:
    """
    Evaluate an alert detectors configuration against data.

    The configuration supports nested AND/OR combinations of detectors.
    Returns a combined result indicating if any breach conditions are met.

    Args:
        config: The alert detectors configuration with AND/OR groups
        data: List of numerical values from the time series
        timestamps: List of timestamp strings corresponding to each data point
        series_label: Label for the series being evaluated
        check_index: Optional specific index to check (default: most recent point)

    Returns:
        DetectorResult with combined breach status and messages
    """
    if not config.groups:
        return DetectorResult(
            is_breaching=False,
            breach_indices=[],
            value=None,
            message="No detectors configured",
        )

    # Evaluate all top-level groups/detectors
    results = []
    for item in config.groups:
        result = _evaluate_detector_or_group(item, data, timestamps, series_label, check_index)
        results.append(result)

    # Combine based on top-level operator
    is_and = config.type == FilterLogicalOperator.AND_ or config.type == "AND"

    if is_and:
        is_breaching = all(r.is_breaching for r in results)

        if is_breaching:
            all_breach_sets = [set(r.breach_indices) for r in results if r.breach_indices]
            if all_breach_sets:
                breach_indices = list(set.intersection(*all_breach_sets))
            else:
                breach_indices = []

            messages = [r.message for r in results if r.message]
            return DetectorResult(
                is_breaching=True,
                breach_indices=sorted(breach_indices),
                value=None,
                message=" AND ".join(messages) if messages else "All detector groups triggered",
            )
        return DetectorResult(is_breaching=False, breach_indices=[], value=None, message=None)
    else:
        is_breaching = any(r.is_breaching for r in results)

        if is_breaching:
            breach_indices = []
            for r in results:
                if r.is_breaching:
                    breach_indices.extend(r.breach_indices)
            breach_indices = sorted(set(breach_indices))

            messages = [r.message for r in results if r.is_breaching and r.message]
            return DetectorResult(
                is_breaching=True,
                breach_indices=breach_indices,
                value=None,
                message=" OR ".join(messages) if messages else "At least one detector group triggered",
            )
        return DetectorResult(is_breaching=False, breach_indices=[], value=None, message=None)


def get_all_breach_points(
    config: AlertDetectorsConfig,
    data: list[float],
    timestamps: list[str],
) -> list[int]:
    """
    Get all breach points for visualization purposes.

    This evaluates each point in the data series and returns indices
    where the combined detector configuration would trigger.

    Args:
        config: The alert detectors configuration
        data: List of numerical values from the time series
        timestamps: List of timestamp strings

    Returns:
        List of indices where breaches occur
    """
    breach_indices = []

    for i in range(len(data)):
        result = evaluate_detectors(config, data, timestamps, series_label="", check_index=i)
        if result.is_breaching:
            breach_indices.append(i)

    return breach_indices
