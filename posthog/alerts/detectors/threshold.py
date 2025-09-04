"""Threshold-based detector - maintains existing alert behavior."""

from .base import BaseDetector, DetectionResult, DetectorType, ValueType


class ThresholdDetector(BaseDetector):
    """Threshold-based detector (maintains existing alert behavior)."""

    @property
    def detector_type(self) -> DetectorType:
        return DetectorType.THRESHOLD

    def validate_config(self) -> None:
        """Validate threshold configuration."""
        bounds = self.config.get("bounds", {})
        lower = bounds.get("lower")
        upper = bounds.get("upper")

        if lower is not None and upper is not None:
            if lower > upper:
                raise ValueError("Lower threshold must be less than upper threshold")

        threshold_type = self.config.get("threshold_type", "absolute")
        if threshold_type not in ["absolute", "percentage"]:
            raise ValueError("threshold_type must be 'absolute' or 'percentage'")

    def detect(
        self, values: list[float], series_name: str = "Series", value_type: ValueType = ValueType.RAW
    ) -> DetectionResult:
        """Run threshold detection."""
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
            current_value = detection_values[-1]
        else:
            current_value = values[-1]

        # Get threshold bounds
        bounds = self.config.get("bounds", {})
        lower = bounds.get("lower")
        upper = bounds.get("upper")
        threshold_type = self.config.get("threshold_type", "absolute")

        # Check for breaches
        breach_messages = []
        is_breach = False

        if lower is not None and current_value < lower:
            is_breach = True
            formatted_value = f"{current_value:.2%}" if threshold_type == "percentage" else current_value
            formatted_bound = f"{lower:.2%}" if threshold_type == "percentage" else lower
            breach_messages.append(
                f"The {value_type.value} value for {series_name} ({formatted_value}) is less than lower threshold ({formatted_bound})"
            )

        if upper is not None and current_value > upper:
            is_breach = True
            formatted_value = f"{current_value:.2%}" if threshold_type == "percentage" else current_value
            formatted_bound = f"{upper:.2%}" if threshold_type == "percentage" else upper
            breach_messages.append(
                f"The {value_type.value} value for {series_name} ({formatted_value}) is more than upper threshold ({formatted_bound})"
            )

        return DetectionResult(
            value=values[-1],  # Always return the raw value
            detector_score=current_value,  # For threshold, score is the same as detection value
            is_breach=is_breach,
            breach_messages=breach_messages,
            metadata={"threshold_type": threshold_type, "bounds": bounds},
        )
