import numpy as np
from pyod.models.pca import PCA

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.PCA)
class PCADetector(BaseDetector):
    """
    PCA-based anomaly detection using PyOD.

    Detects anomalies as points that don't fit the principal components
    of the data. Uses reconstruction error — anomalies have high error
    when projected back from the reduced space.

    Config:
        threshold: float - Anomaly probability threshold (default: 0.9)
    """

    MIN_SAMPLES = 10

    def detect(self, data: np.ndarray) -> DetectionResult:
        if not self._validate_data(data, min_length=self.MIN_SAMPLES):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        threshold = self.config.get("threshold", 0.9)

        if data.ndim == 1:
            data = data.reshape(-1, 1)

        model = PCA()
        model.fit(data)

        last_point = data[-1:, :]
        prob = float(model.predict_proba(last_point)[0, 1])
        is_anomaly = prob > threshold

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=prob,
            triggered_indices=[len(data) - 1] if is_anomaly else [],
            all_scores=[prob],
            metadata={"raw_score": float(model.decision_function(last_point)[0])},
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        if not self._validate_data(data, min_length=self.MIN_SAMPLES):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        threshold = self.config.get("threshold", 0.9)

        if data.ndim == 1:
            data = data.reshape(-1, 1)

        model = PCA()
        model.fit(data)

        probs = model.predict_proba(data)[:, 1]
        triggered = [i for i, p in enumerate(probs) if p > threshold]

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=float(probs[-1]) if len(probs) > 0 else None,
            triggered_indices=triggered,
            all_scores=[float(p) for p in probs],
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": "pca",
            "threshold": 0.9,
        }
