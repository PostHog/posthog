import numpy as np

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.THRESHOLD)
class ThresholdDetector(BaseDetector):
    """
    Threshold-based anomaly detection.

    Checks if values fall outside specified upper/lower bounds.
    This is the simplest detector and mirrors the existing alert threshold logic.

    Config:
        threshold_type: "absolute" or "percentage"
        bounds: {"lower": float | None, "upper": float | None}
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Check if the latest point breaches thresholds."""
        if not self._validate_data(data, min_length=1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)

        # Get bounds from config
        bounds = self.config.get("bounds", {})
        lower = bounds.get("lower")
        upper = bounds.get("upper")

        # Handle percentage thresholds by computing relative bounds
        threshold_type = self.config.get("threshold_type", "absolute")
        if threshold_type == "percentage" and len(data) >= 2:
            # For percentage, bounds are relative to previous value
            prev_value = data[-2]
            if lower is not None:
                lower = prev_value * (1 - lower)
            if upper is not None:
                upper = prev_value * (1 + upper)

        value = data[-1] if data.ndim == 1 else data[-1, 0]

        is_anomaly = False
        if lower is not None and value < lower:
            is_anomaly = True
        if upper is not None and value > upper:
            is_anomaly = True

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=float(value),
            triggered_indices=[len(data) - 1] if is_anomaly else [],
            all_scores=[float(value)],
            metadata={"lower": lower, "upper": upper, "value": float(value)},
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Check all points against thresholds."""
        if not self._validate_data(data, min_length=1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)

        bounds = self.config.get("bounds", {})
        lower = bounds.get("lower")
        upper = bounds.get("upper")
        threshold_type = self.config.get("threshold_type", "absolute")

        triggered = []
        scores: list[float | None] = []

        # For 2D data from preprocessing, use first column
        values = data if data.ndim == 1 else data[:, 0]

        for i, val in enumerate(values):
            current_lower = lower
            current_upper = upper

            # For percentage thresholds, compute relative to previous value
            if threshold_type == "percentage" and i > 0:
                prev_val = values[i - 1]
                if lower is not None:
                    current_lower = prev_val * (1 - lower)
                if upper is not None:
                    current_upper = prev_val * (1 + upper)

            is_breach = False
            if current_lower is not None and val < current_lower:
                is_breach = True
            if current_upper is not None and val > current_upper:
                is_breach = True

            if is_breach:
                triggered.append(i)
            scores.append(float(val))

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=float(values[-1]) if len(values) > 0 else None,
            triggered_indices=triggered,
            all_scores=scores,
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.THRESHOLD.value,
            "threshold_type": "absolute",
            "bounds": {"lower": None, "upper": None},
        }
