import numpy as np
from pyod.models.knn import KNN

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.KNN)
class KNNDetector(BaseDetector):
    """
    K-Nearest Neighbors (KNN) based anomaly detection using PyOD.

    KNN uses the distance to the k-th nearest neighbor as the anomaly score.
    Points that are far from their neighbors are considered anomalies.

    Scores are normalized to [0, 1] probabilities using pyod's
    predict_proba (erf-based conversion).

    Config:
        threshold: float - Anomaly probability threshold (default: 0.9)
        n_neighbors: int - Number of neighbors to consider (default: 5)
        method: str - Distance method: 'largest', 'mean', 'median' (default: 'largest')
    """

    MIN_SAMPLES = 10

    def detect(self, data: np.ndarray) -> DetectionResult:
        if not self._validate_data(data, min_length=self.MIN_SAMPLES):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        threshold = self.config.get("threshold", 0.9)
        n_neighbors = self.config.get("n_neighbors", 5)
        method = self.config.get("method", "largest")

        n_neighbors = min(n_neighbors, len(data) - 1)

        if data.ndim == 1:
            data = data.reshape(-1, 1)

        model = KNN(
            n_neighbors=n_neighbors,
            method=method,
        )
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
        n_neighbors = self.config.get("n_neighbors", 5)
        method = self.config.get("method", "largest")

        n_neighbors = min(n_neighbors, len(data) - 1)

        if data.ndim == 1:
            data = data.reshape(-1, 1)

        model = KNN(
            n_neighbors=n_neighbors,
            method=method,
        )
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
            "type": DetectorType.KNN.value,
            "threshold": 0.9,
            "n_neighbors": 5,
            "method": "largest",
        }
