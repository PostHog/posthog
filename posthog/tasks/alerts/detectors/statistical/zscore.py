import numpy as np

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import PointScore, RollingWindowDetector
from posthog.tasks.alerts.detectors.registry import register_detector


def _zscore_to_probability(z_score: float, window_zscores: np.ndarray) -> float:
    """Normalize a z-score to a [0, 1] anomaly probability.

    Uses min-max normalization against the training window z-scores,
    consistent with PyOD's default ``linear`` method. The score represents
    where the current z-score falls relative to the range observed in the
    training window: 0 means at or below the minimum, 1 means at or above
    the maximum.
    """
    min_z = float(window_zscores.min())
    max_z = float(window_zscores.max())
    if max_z == min_z:
        return 1.0 if z_score > max_z else 0.0
    return float(np.clip((z_score - min_z) / (max_z - min_z), 0.0, 1.0))


@register_detector(DetectorType.ZSCORE)
class ZScoreDetector(RollingWindowDetector):
    """
    Z-Score based anomaly detector.

    Detects anomalies by calculating how many standard deviations
    a value is from the rolling mean.

    Scores are normalized to [0, 1] using min-max normalization against
    the training window z-scores (consistent with PyOD's default ``linear``
    method).

    Config:
        threshold: float - Anomaly probability threshold (default: 0.95)
        window: int - Rolling window size (default: 30)
    """

    def score_point(self, window_data: np.ndarray, value: float) -> PointScore:
        mean = np.mean(window_data)
        std = np.std(window_data)

        if std == 0:
            return PointScore(
                probability=1.0 if abs(value - mean) > 0 else 0.0,
                metadata={"mean": float(mean), "std": 0.0, "value": value, "raw_zscore": None},
            )

        z_score = abs((value - mean) / std)
        window_zscores = np.abs((window_data - mean) / std)

        return PointScore(
            probability=_zscore_to_probability(z_score, window_zscores),
            metadata={
                "mean": float(mean),
                "std": float(std),
                "value": value,
                "raw_zscore": float(z_score),
            },
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.ZSCORE.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "window": 30,
            "preprocessing": {"diffs_n": 1},
        }
