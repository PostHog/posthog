import numpy as np
from pyod.models.mad import MAD

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.MAD)
class MADDetector(BaseDetector):
    """
    Median Absolute Deviation (MAD) anomaly detector.

    Uses pyod's MAD implementation to detect outliers based on
    the modified z-score: 0.6745 * |x - median| / MAD.

    More robust than z-score because it uses median instead of mean,
    making it resistant to outliers skewing the baseline.

    Scores are normalized to [0, 1] probabilities using pyod's
    predict_proba (erf-based conversion).

    Config:
        threshold: float - Anomaly probability threshold (default: 0.9)
        window: int - Rolling window size (default: 30)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", 0.9)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        # Use rolling window (exclude current point) to fit the model
        window_data = values[-(window + 1) : -1]
        current_value = values[-1]

        clf = MAD()
        clf.fit(window_data.reshape(-1, 1))

        # Get normalized probability score via pyod's erf-based conversion
        test_point = np.array([[current_value]])
        prob = float(clf.predict_proba(test_point)[0, 1])
        is_anomaly = prob > threshold

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=prob,
            triggered_indices=[len(values) - 1] if is_anomaly else [],
            all_scores=[prob],
            metadata={
                "median": float(clf.median_),
                "median_abs_deviation": float(clf.median_diff_),
                "value": float(current_value),
                "raw_score": float(clf.decision_function(test_point)[0]),
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", 0.9)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        triggered = []
        scores: list[float | None] = [None] * window

        for i in range(window, len(values)):
            window_data = values[i - window : i]
            current_val = values[i]

            clf = MAD()
            clf.fit(window_data.reshape(-1, 1))

            test_point = np.array([[current_val]])
            prob = float(clf.predict_proba(test_point)[0, 1])
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
            "type": DetectorType.MAD.value,
            "threshold": 0.9,
            "window": 30,
        }
