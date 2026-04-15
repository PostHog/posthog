from typing import Any

import numpy as np
from scipy.special import erf

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import register_detector


def _iqr_fence_distances(
    window_data: np.ndarray, lower_fence: float, upper_fence: float, iqr: float | np.floating
) -> np.ndarray:
    """Compute IQR fence distances for all points in a window."""
    return np.where(
        window_data < lower_fence,
        (lower_fence - window_data) / iqr if iqr > 0 else 0.0,
        np.where(window_data > upper_fence, (window_data - upper_fence) / iqr if iqr > 0 else 0.0, 0.0),
    )


def _iqr_distance_to_probability(distance: float, window_distances: np.ndarray) -> float:
    """Normalize an IQR fence distance to a [0, 1] anomaly probability.

    Uses pyod's 'unify' approach: standardize the distance against the
    distribution of distances observed in the training window, then apply erf.
    """
    mean_d = float(window_distances.mean())
    std_d = float(window_distances.std())
    if std_d == 0:
        return 1.0 if distance > mean_d else 0.0
    standardized = (distance - mean_d) / std_d
    return float(np.clip(erf(standardized / np.sqrt(2)), 0.0, 1.0))


@register_detector(DetectorType.IQR)
class IQRDetector(BaseDetector):
    """
    Interquartile Range (IQR) based anomaly detection.

    Classic outlier detection using Tukey's fences:
    - Values below Q1 - multiplier*IQR are anomalies
    - Values above Q3 + multiplier*IQR are anomalies

    Scores are normalized to [0, 1] probabilities using pyod's 'unify'
    approach (standardize against training window distances, then erf).

    Config:
        threshold: float - Anomaly probability threshold (default: 0.95)
        multiplier: float - IQR multiplier for fences (default: 1.5)
        window: int - Rolling window size (default: 30)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        multiplier = self.config.get("multiplier", 1.5)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        window_data = values[-(window + 1) : -1]
        q1 = np.percentile(window_data, 25)
        q3 = np.percentile(window_data, 75)
        iqr = q3 - q1

        lower_fence = q1 - multiplier * iqr
        upper_fence = q3 + multiplier * iqr

        current_value = values[-1]

        # Raw distance from nearest fence, normalized by IQR
        if iqr == 0:
            raw_distance = 0.0
        elif current_value < lower_fence:
            raw_distance = (lower_fence - current_value) / iqr
        elif current_value > upper_fence:
            raw_distance = (current_value - upper_fence) / iqr
        else:
            raw_distance = 0.0

        window_distances = _iqr_fence_distances(window_data, lower_fence, upper_fence, iqr)

        prob = _iqr_distance_to_probability(raw_distance, window_distances)
        is_anomaly = prob > threshold

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=prob,
            triggered_indices=[len(values) - 1] if is_anomaly else [],
            all_scores=[prob],
            metadata={
                "q1": float(q1),
                "q3": float(q3),
                "iqr": float(iqr),
                "lower_fence": float(lower_fence),
                "upper_fence": float(upper_fence),
                "value": float(current_value),
                "raw_distance": raw_distance,
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        multiplier = self.config.get("multiplier", 1.5)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        triggered = []
        scores: list[float | None] = [None] * window

        for i in range(window, len(values)):
            window_data = values[i - window : i]
            q1 = np.percentile(window_data, 25)
            q3 = np.percentile(window_data, 75)
            iqr = q3 - q1

            lower_fence = q1 - multiplier * iqr
            upper_fence = q3 + multiplier * iqr

            val = values[i]

            if iqr == 0:
                raw_distance = 0.0
            elif val < lower_fence:
                raw_distance = (lower_fence - val) / iqr
            elif val > upper_fence:
                raw_distance = (val - upper_fence) / iqr
            else:
                raw_distance = 0.0

            window_distances = np.where(
                window_data < lower_fence,
                (lower_fence - window_data) / iqr if iqr > 0 else 0.0,
                np.where(window_data > upper_fence, (window_data - upper_fence) / iqr if iqr > 0 else 0.0, 0.0),
            )

            prob = _iqr_distance_to_probability(raw_distance, window_distances)
            scores.append(prob)
            if prob > threshold:
                triggered.append(i)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
        )

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {
            "type": DetectorType.IQR.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "multiplier": 1.5,
            "window": 30,
        }
