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
        upper_bound: float | None - Values above this are anomalies
        lower_bound: float | None - Values below this are anomalies
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Check if the latest point breaches thresholds."""
        if not self._validate_data(data, min_length=1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)

        # Get bounds from config
        lower = self.config.get("lower_bound")
        upper = self.config.get("upper_bound")

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
            metadata={"lower_bound": lower, "upper_bound": upper, "value": float(value)},
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Check all points against thresholds."""
        if not self._validate_data(data, min_length=1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)

        lower = self.config.get("lower_bound")
        upper = self.config.get("upper_bound")

        triggered = []
        scores: list[float | None] = []

        # For 2D data from preprocessing, use first column
        values = data if data.ndim == 1 else data[:, 0]

        for i, val in enumerate(values):
            is_breach = False
            if lower is not None and val < lower:
                is_breach = True
            if upper is not None and val > upper:
                is_breach = True

            scores.append(float(val))
            if is_breach:
                triggered.append(i)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
            metadata={"lower_bound": lower, "upper_bound": upper},
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.THRESHOLD.value,
            "lower_bound": None,
            "upper_bound": None,
        }
