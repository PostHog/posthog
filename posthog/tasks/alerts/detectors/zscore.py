import math
from statistics import mean, stdev

from posthog.schema import (
    DetectorDirection,
    DetectorType,
    ZScoreDetectorConfig,
)
from posthog.tasks.alerts.detectors.base import BaseDetector, DetectorResult


class ZScoreDetector(BaseDetector):
    """
    Z-Score based anomaly detector.

    Calculates the z-score of the current value relative to a rolling window
    of historical data. Triggers when the z-score exceeds the configured threshold.

    Z-score = (value - mean) / std_deviation

    A z-score of 2.0 means the value is 2 standard deviations from the mean,
    which is unusual (occurs ~5% of the time in a normal distribution).
    """

    detector_type = DetectorType.ZSCORE

    def __init__(self, config: ZScoreDetectorConfig):
        self.lookback_periods: int = config.lookback_periods
        self.z_threshold: float = config.z_threshold
        self.direction: DetectorDirection = config.direction

    def _calculate_zscore(self, value: float, historical_data: list[float]) -> float | None:
        """Calculate z-score for a value given historical data."""
        if len(historical_data) < 2:
            return None

        data_mean = mean(historical_data)
        data_std = stdev(historical_data)

        if data_std == 0:
            # All values are identical - can't calculate meaningful z-score
            return 0.0 if value == data_mean else float("inf") if value > data_mean else float("-inf")

        return (value - data_mean) / data_std

    def _is_zscore_breaching(self, z_score: float) -> bool:
        """Check if z-score exceeds threshold in the configured direction."""
        match self.direction:
            case DetectorDirection.ABOVE:
                return z_score > self.z_threshold
            case DetectorDirection.BELOW:
                return z_score < -self.z_threshold
            case DetectorDirection.BOTH:
                return abs(z_score) > self.z_threshold
            case _:
                return False

    def evaluate(
        self,
        data: list[float],
        timestamps: list[str],
        series_label: str,
        check_index: int | None = None,
    ) -> DetectorResult:
        min_points = self.get_minimum_data_points()

        if len(data) < min_points:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message=f"Insufficient data: need at least {min_points} points, have {len(data)}",
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

        # Get the value to check
        check_value = data[actual_index]

        # Get historical data for z-score calculation (excluding the check point)
        # Use data before the check point, up to lookback_periods
        historical_start = max(0, actual_index - self.lookback_periods)
        historical_data = data[historical_start:actual_index]

        if len(historical_data) < 2:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message="Insufficient historical data for z-score calculation",
            )

        z_score = self._calculate_zscore(check_value, historical_data)

        if z_score is None:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message="Could not calculate z-score",
            )

        is_breaching = self._is_zscore_breaching(z_score)

        if is_breaching:
            direction_text = "above" if z_score > 0 else "below"
            return DetectorResult(
                is_breaching=True,
                breach_indices=[actual_index],
                value=z_score,
                message=f"Value ({series_label}) has z-score of {z_score:.2f}, which is {direction_text} the threshold of {self.z_threshold}",
            )

        return DetectorResult(
            is_breaching=False,
            breach_indices=[],
            value=z_score,
            message=None,
        )

    def get_breach_points(
        self,
        data: list[float],
        timestamps: list[str],
    ) -> list[int]:
        breach_indices = []
        min_history = 2  # Need at least 2 points to calculate std

        for i in range(len(data)):
            # Get historical data for this point
            historical_start = max(0, i - self.lookback_periods)
            historical_data = data[historical_start:i]

            if len(historical_data) < min_history:
                continue

            z_score = self._calculate_zscore(data[i], historical_data)

            if z_score is not None and self._is_zscore_breaching(z_score):
                breach_indices.append(i)

        return breach_indices

    @classmethod
    def get_minimum_data_points(cls) -> int:
        # Need at least 3 points: 2 for historical mean/std calculation + 1 to evaluate
        return 3
