from posthog.schema import (
    DetectorType,
    InsightThresholdType,
    InsightsThresholdBounds,
    ThresholdDetectorConfig,
)
from posthog.tasks.alerts.detectors.base import BaseDetector, DetectorResult


class ThresholdDetector(BaseDetector):
    """
    Threshold-based detector that triggers when values exceed upper or lower bounds.

    This is the simplest detector type - it compares each value against
    configured upper and/or lower thresholds.
    """

    detector_type = DetectorType.THRESHOLD

    def __init__(self, config: ThresholdDetectorConfig):
        self.bounds: InsightsThresholdBounds = config.bounds
        self.threshold_type: InsightThresholdType = config.threshold_type

    def evaluate(
        self,
        data: list[float],
        timestamps: list[str],
        series_label: str,
        check_index: int | None = None,
    ) -> DetectorResult:
        if not data:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message="No data available for evaluation",
            )

        # Default to checking the most recent point
        if check_index is None:
            check_index = -1

        # Resolve negative indices
        actual_index = check_index if check_index >= 0 else len(data) + check_index
        if actual_index < 0 or actual_index >= len(data):
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message=f"Check index {check_index} out of range for data length {len(data)}",
            )

        value = data[actual_index]
        is_percentage = self.threshold_type == InsightThresholdType.PERCENTAGE
        formatted_value = f"{value:.2%}" if is_percentage else value

        # Check lower bound
        if self.bounds.lower is not None and value < self.bounds.lower:
            lower_formatted = f"{self.bounds.lower:.2%}" if is_percentage else self.bounds.lower
            return DetectorResult(
                is_breaching=True,
                breach_indices=[actual_index],
                value=value,
                message=f"Value ({series_label}) of {formatted_value} is below lower threshold of {lower_formatted}",
            )

        # Check upper bound
        if self.bounds.upper is not None and value > self.bounds.upper:
            upper_formatted = f"{self.bounds.upper:.2%}" if is_percentage else self.bounds.upper
            return DetectorResult(
                is_breaching=True,
                breach_indices=[actual_index],
                value=value,
                message=f"Value ({series_label}) of {formatted_value} is above upper threshold of {upper_formatted}",
            )

        return DetectorResult(
            is_breaching=False,
            breach_indices=[],
            value=value,
            message=None,
        )

    def get_breach_points(
        self,
        data: list[float],
        timestamps: list[str],
    ) -> list[int]:
        breach_indices = []

        for i, value in enumerate(data):
            is_breaching = False

            if self.bounds.lower is not None and value < self.bounds.lower:
                is_breaching = True
            elif self.bounds.upper is not None and value > self.bounds.upper:
                is_breaching = True

            if is_breaching:
                breach_indices.append(i)

        return breach_indices
