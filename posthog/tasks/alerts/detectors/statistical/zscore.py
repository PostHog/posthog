import numpy as np
from scipy.special import erf

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import register_detector


def _zscore_to_probability(z_score: float, window_zscores: np.ndarray) -> float:
    """Normalize a z-score to a [0, 1] anomaly probability.

    Uses pyod's 'unify' approach: standardize the raw z-score against the
    distribution of z-scores observed in the training window, then apply erf.
    This asks "how unusual is this z-score compared to what we normally see?"
    rather than mapping the raw z-score directly (which produces a fixed ~5%
    false-positive rate regardless of data stability).
    """
    mean_z = float(window_zscores.mean())
    std_z = float(window_zscores.std())
    if std_z == 0:
        return 1.0 if z_score > mean_z else 0.0
    standardized = (z_score - mean_z) / std_z
    return float(np.clip(erf(standardized / np.sqrt(2)), 0.0, 1.0))


@register_detector(DetectorType.ZSCORE)
class ZScoreDetector(BaseDetector):
    """
    Z-Score based anomaly detector.

    Detects anomalies by calculating how many standard deviations
    a value is from the rolling mean.

    Scores are normalized to [0, 1] probabilities using pyod's 'unify'
    approach (standardize against training window z-scores, then erf).

    Config:
        threshold: float - Anomaly probability threshold (default: 0.95)
        window: int - Rolling window size (default: 30)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Check if the most recent point is an anomaly based on z-score."""
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        # Use rolling window for mean/std (exclude current point)
        window_data = values[-(window + 1) : -1]
        mean = np.mean(window_data)
        std = np.std(window_data)

        current_value = values[-1]

        if std == 0:
            is_anomaly = abs(current_value - mean) > 0
            return DetectionResult(
                is_anomaly=is_anomaly,
                score=1.0 if is_anomaly else 0.0,
                triggered_indices=[len(values) - 1] if is_anomaly else [],
                all_scores=[1.0 if is_anomaly else 0.0],
                metadata={"mean": float(mean), "std": 0.0, "value": float(current_value), "raw_zscore": None},
            )

        z_score = abs((current_value - mean) / std)
        window_zscores = np.abs((window_data - mean) / std)
        prob = _zscore_to_probability(z_score, window_zscores)

        return DetectionResult(
            is_anomaly=prob > threshold,
            score=prob,
            triggered_indices=[len(values) - 1] if prob > threshold else [],
            all_scores=[prob],
            metadata={
                "mean": float(mean),
                "std": float(std),
                "value": float(current_value),
                "raw_zscore": float(z_score),
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Check all points for z-score anomalies."""
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        triggered = []
        scores: list[float | None] = [None] * window

        for i in range(window, len(values)):
            window_data = values[i - window : i]
            mean = np.mean(window_data)
            std = np.std(window_data)

            current_val = values[i]

            if std == 0:
                if abs(current_val - mean) > 0:
                    scores.append(1.0)
                    triggered.append(i)
                else:
                    scores.append(0.0)
                continue

            z_score = abs((current_val - mean) / std)
            window_zscores = np.abs((window_data - mean) / std)
            prob = _zscore_to_probability(z_score, window_zscores)
            scores.append(prob)

            if prob > threshold:
                triggered.append(i)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
            metadata={"threshold": threshold, "window": window},
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.ZSCORE.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "window": 30,
            "preprocessing": {"diffs_n": 1},
        }
