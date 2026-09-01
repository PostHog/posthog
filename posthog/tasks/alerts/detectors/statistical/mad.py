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
        threshold: float - Anomaly probability threshold (default: 0.95)
        window: int - Rolling window size (default: 30)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        window = self.config.get("window", 30)
        # preprocess() only ever runs a single first-difference pass when diffs_n is truthy
        # (it's a boolean toggle, not a pass count), so exactly one synthetic leading point
        # is introduced regardless of the configured magnitude.
        diffs_n = 1 if self.preprocessing_config.get("diffs_n") else 0
        offset = max(self.training_offset, 1)

        if not self._validate_data(data, min_length=window + offset + diffs_n):
            return DetectionResult(is_anomaly=False)

        original_length = len(data)
        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]
        # Differencing prepends synthetic (zero-valued) points to keep the array
        # length unchanged - drop them so the training window only ever sees
        # genuine differenced values.
        values = values[diffs_n:]

        # Use rolling window, honoring training_offset to exclude points closest
        # to the one being scored, so a live check agrees with detect_batch()
        window_data = values[-(window + offset) : -offset]
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
            triggered_indices=[original_length - 1] if is_anomaly else [],
            all_scores=[prob],
            metadata={
                "median": float(clf.median_),
                "median_abs_deviation": float(clf.median_diff_),
                "value": float(current_value),
                "raw_score": float(clf.decision_function(test_point)[0]),
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        window = self.config.get("window", 30)
        # preprocess() only ever runs a single first-difference pass when diffs_n is truthy
        # (it's a boolean toggle, not a pass count), so exactly one synthetic leading point
        # is introduced regardless of the configured magnitude.
        diffs_n = 1 if self.preprocessing_config.get("diffs_n") else 0
        offset = max(self.training_offset, 1)

        if not self._validate_data(data, min_length=window + offset + diffs_n):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]
        # Keep indices aligned with the original series: scores/triggers below
        # are shifted back by diffs_n before being returned.
        values = values[diffs_n:]

        triggered = []
        scores: list[float | None] = [None] * (diffs_n + window + offset - 1)

        for i in range(window + offset - 1, len(values)):
            window_data = values[i - window - offset + 1 : i - offset + 1]
            current_val = values[i]

            clf = MAD()
            clf.fit(window_data.reshape(-1, 1))

            test_point = np.array([[current_val]])
            prob = float(clf.predict_proba(test_point)[0, 1])
            scores.append(prob)

            if prob > threshold:
                triggered.append(i + diffs_n)

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
            "threshold": cls.DEFAULT_THRESHOLD,
            "window": 30,
            "preprocessing": {"diffs_n": 1},
        }
