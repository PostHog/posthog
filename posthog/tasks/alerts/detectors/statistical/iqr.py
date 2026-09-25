from typing import Any

import numpy as np
from scipy.special import erf

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import PointScore, RollingWindowDetector
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


def _fence_distance(
    value: float | np.floating, lower_fence: float, upper_fence: float, iqr: float | np.floating
) -> float:
    """Distance of a single value past its nearest fence, normalized by the IQR."""
    if iqr == 0:
        return 0.0
    if value < lower_fence:
        return float((lower_fence - value) / iqr)
    if value > upper_fence:
        return float((value - upper_fence) / iqr)
    return 0.0


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
class IQRDetector(RollingWindowDetector):
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

    def score_point(self, window_data: np.ndarray, value: float) -> PointScore:
        multiplier = self.config.get("multiplier", 1.5)
        q1 = np.percentile(window_data, 25)
        q3 = np.percentile(window_data, 75)
        iqr = q3 - q1

        lower_fence = q1 - multiplier * iqr
        upper_fence = q3 + multiplier * iqr

        raw_distance = _fence_distance(value, lower_fence, upper_fence, iqr)
        window_distances = _iqr_fence_distances(window_data, lower_fence, upper_fence, iqr)

        return PointScore(
            probability=_iqr_distance_to_probability(raw_distance, window_distances),
            metadata={
                "q1": float(q1),
                "q3": float(q3),
                "iqr": float(iqr),
                "lower_fence": float(lower_fence),
                "upper_fence": float(upper_fence),
                "value": value,
                "raw_distance": raw_distance,
            },
        )

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {
            "type": DetectorType.IQR.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "multiplier": 1.5,
            "window": 30,
        }
