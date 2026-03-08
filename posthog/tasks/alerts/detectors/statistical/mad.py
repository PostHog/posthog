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

    Config:
        threshold: float - Modified z-score threshold (default: 3.5)
        window: int - Rolling window size (default: 30)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", 3.5)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        # Use rolling window (exclude current point) to fit the model
        window_data = values[-(window + 1) : -1]
        current_value = values[-1]

        clf = MAD(threshold=threshold)
        clf.fit(window_data.reshape(-1, 1))

        # Score the current point against the fitted model
        score = clf.decision_function(np.array([[current_value]]))[0]
        is_anomaly = score > threshold

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=float(score),
            triggered_indices=[len(values) - 1] if is_anomaly else [],
            all_scores=[float(score)],
            metadata={
                "median": float(clf.median_),
                "median_abs_deviation": float(clf.median_diff_),
                "value": float(current_value),
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", 3.5)
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

            clf = MAD(threshold=threshold)
            clf.fit(window_data.reshape(-1, 1))

            score = clf.decision_function(np.array([[current_val]]))[0]
            scores.append(float(score))

            if score > threshold:
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
            "threshold": 3.5,
            "window": 30,
        }
