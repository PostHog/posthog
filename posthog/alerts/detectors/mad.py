"""Median Absolute Deviation (MAD) based anomaly detector. More robust to outliers than z-score."""

import numpy as np

from .base import BaseDetector, DetectionDirection, DetectionResult, DetectorType, ValueType


class MADDetector(BaseDetector):
    """Median Absolute Deviation (MAD) based anomaly detector. More robust to outliers than z-score."""

    @property
    def detector_type(self) -> DetectorType:
        return DetectorType.MAD

    def validate_config(self) -> None:
        """Validate MAD configuration."""
        threshold = self.config.get("threshold", 3.0)
        if not isinstance(threshold, int | float) or threshold <= 0:
            raise ValueError("MAD threshold must be a positive number")

        direction = self.config.get("direction", "both")
        if direction not in ["up", "down", "both"]:
            raise ValueError("direction must be 'up', 'down', or 'both'")

        min_samples = self.config.get("min_samples", 10)
        if not isinstance(min_samples, int) or min_samples < 2:
            raise ValueError("min_samples must be an integer >= 2")

        window_size = self.config.get("window_size", 100)
        if not isinstance(window_size, int) or window_size < min_samples:
            raise ValueError("window_size must be >= min_samples")

    def detect(
        self, values: list[float], series_name: str = "Series", value_type: ValueType = ValueType.RAW
    ) -> DetectionResult:
        """Run MAD based detection."""
        if not values:
            return DetectionResult(value=None, detector_score=None, is_breach=False, breach_messages=[], metadata={})

        # Use appropriate values based on value_type
        if value_type == ValueType.DELTA:
            detection_values = self._compute_deltas(values)
            if not detection_values:
                return DetectionResult(
                    value=values[-1],
                    detector_score=None,
                    is_breach=False,
                    breach_messages=[],
                    metadata={"insufficient_data": True},
                )
        else:
            detection_values = values

        # Get configuration
        threshold = self.config.get("threshold", 3.0)
        direction = DetectionDirection(self.config.get("direction", "both"))
        min_samples = self.config.get("min_samples", 10)
        window_size = self.config.get("window_size", 100)

        # Check if we have enough data
        if len(detection_values) < min_samples:
            return DetectionResult(
                value=values[-1],
                detector_score=None,
                is_breach=False,
                breach_messages=[],
                metadata={"insufficient_samples": len(detection_values), "min_required": min_samples},
            )

        # Use rolling window
        window_values = detection_values[-window_size:]
        current_value = window_values[-1]
        historical_values = window_values[:-1]  # All but the last value for baseline

        # Calculate MAD score
        if len(historical_values) == 0:
            return DetectionResult(
                value=values[-1],
                detector_score=0.0,
                is_breach=False,
                breach_messages=[],
                metadata={"insufficient_history": True},
            )

        hist_array = np.array(historical_values)
        median = np.median(hist_array)

        # Calculate MAD: median of absolute deviations from median
        absolute_deviations = np.abs(hist_array - median)
        mad = np.median(absolute_deviations)

        if mad == 0:
            # No variation in historical data
            mad_score = 0.0
        else:
            # Modified z-score using MAD
            # Scale factor 1.4826 makes MAD consistent with std for normal distribution
            mad_score = 0.6745 * (current_value - median) / mad

        # Check for breach based on direction
        is_breach = False
        breach_messages = []

        if direction in [DetectionDirection.UP, DetectionDirection.BOTH]:
            if mad_score > threshold:
                is_breach = True
                breach_messages.append(
                    f"The {value_type.value} value for {series_name} ({current_value:.4f}) has a MAD score of {mad_score:.2f}, which exceeds the upper threshold of {threshold}"
                )

        if direction in [DetectionDirection.DOWN, DetectionDirection.BOTH]:
            if mad_score < -threshold:
                is_breach = True
                breach_messages.append(
                    f"The {value_type.value} value for {series_name} ({current_value:.4f}) has a MAD score of {mad_score:.2f}, which is below the lower threshold of -{threshold}"
                )

        return DetectionResult(
            value=values[-1],  # Always return raw value
            detector_score=mad_score,
            is_breach=is_breach,
            breach_messages=breach_messages,
            metadata={
                "median": median,
                "mad": mad,
                "threshold": threshold,
                "direction": direction.value,
                "samples_used": len(historical_values),
            },
        )
