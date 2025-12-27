import numpy as np

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.IQR)
class IQRDetector(BaseDetector):
    """
    Interquartile Range (IQR) based anomaly detection.

    Classic outlier detection using Tukey's fences:
    - Values below Q1 - multiplier*IQR are anomalies
    - Values above Q3 + multiplier*IQR are anomalies

    Common multipliers:
    - 1.5 for "mild" outliers (standard box plot whiskers)
    - 3.0 for "extreme" outliers

    Config:
        multiplier: float - IQR multiplier (default: 1.5)
        window: int - Rolling window size (default: 30)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Check if the latest point is an IQR anomaly."""
        multiplier = self.config.get("multiplier", 1.5)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        # Use rolling window (exclude current point)
        window_data = values[-(window + 1) : -1]
        q1 = np.percentile(window_data, 25)
        q3 = np.percentile(window_data, 75)
        iqr = q3 - q1

        lower_fence = q1 - multiplier * iqr
        upper_fence = q3 + multiplier * iqr

        current_value = values[-1]
        is_anomaly = current_value < lower_fence or current_value > upper_fence

        # Score is distance from nearest fence, normalized by IQR
        if iqr == 0:
            score = 0.0
        elif current_value < lower_fence:
            score = (lower_fence - current_value) / iqr
        elif current_value > upper_fence:
            score = (current_value - upper_fence) / iqr
        else:
            score = 0.0

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=float(score),
            triggered_indices=[len(values) - 1] if is_anomaly else [],
            all_scores=[float(score)],
            metadata={
                "q1": float(q1),
                "q3": float(q3),
                "iqr": float(iqr),
                "lower_fence": float(lower_fence),
                "upper_fence": float(upper_fence),
                "value": float(current_value),
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Check all points for IQR anomalies."""
        multiplier = self.config.get("multiplier", 1.5)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        triggered = []
        scores: list[float | None] = [None] * window  # Pad initial window

        for i in range(window, len(values)):
            window_data = values[i - window : i]
            q1 = np.percentile(window_data, 25)
            q3 = np.percentile(window_data, 75)
            iqr = q3 - q1

            lower_fence = q1 - multiplier * iqr
            upper_fence = q3 + multiplier * iqr

            val = values[i]
            is_outlier = val < lower_fence or val > upper_fence

            # Calculate score
            if iqr == 0:
                score = 0.0
            elif val < lower_fence:
                score = (lower_fence - val) / iqr
            elif val > upper_fence:
                score = (val - upper_fence) / iqr
            else:
                score = 0.0

            scores.append(float(score))
            if is_outlier:
                triggered.append(i)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.IQR.value,
            "multiplier": 1.5,
            "window": 30,
        }
