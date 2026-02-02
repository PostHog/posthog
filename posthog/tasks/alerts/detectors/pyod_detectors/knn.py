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

    Config:
        contamination: float - Expected proportion of outliers (default: 0.1)
        n_neighbors: int - Number of neighbors to consider (default: 5)
        method: str - Distance method: 'largest', 'mean', 'median' (default: 'largest')
    """

    MIN_SAMPLES = 10  # Minimum samples needed for training

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Train on all data and check if the latest point is an anomaly."""
        if not self._validate_data(data, min_length=self.MIN_SAMPLES):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)

        contamination = self.config.get("contamination", 0.1)
        n_neighbors = self.config.get("n_neighbors", 5)
        method = self.config.get("method", "largest")

        # Ensure n_neighbors doesn't exceed data size - 1
        n_neighbors = min(n_neighbors, len(data) - 1)

        # Reshape for sklearn if 1D
        if data.ndim == 1:
            data = data.reshape(-1, 1)

        # Train on all data
        model = KNN(
            contamination=contamination,
            n_neighbors=n_neighbors,
            method=method,
        )
        model.fit(data)

        # Predict on last point
        last_point = data[-1:, :]
        prediction = model.predict(last_point)[0]
        score = model.decision_function(last_point)[0]

        # PyOD: prediction=1 means outlier, score is decision function value
        is_anomaly = prediction == 1

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=float(score),
            triggered_indices=[len(data) - 1] if is_anomaly else [],
            all_scores=[float(score)],
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Train on all data and identify all anomalies."""
        if not self._validate_data(data, min_length=self.MIN_SAMPLES):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)

        contamination = self.config.get("contamination", 0.1)
        n_neighbors = self.config.get("n_neighbors", 5)
        method = self.config.get("method", "largest")

        # Ensure n_neighbors doesn't exceed data size - 1
        n_neighbors = min(n_neighbors, len(data) - 1)

        # Reshape for sklearn if 1D
        if data.ndim == 1:
            data = data.reshape(-1, 1)

        model = KNN(
            contamination=contamination,
            n_neighbors=n_neighbors,
            method=method,
        )
        model.fit(data)

        predictions = model.predict(data)
        scores = model.decision_function(data)

        triggered = [i for i, p in enumerate(predictions) if p == 1]

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=float(scores[-1]) if len(scores) > 0 else None,
            triggered_indices=triggered,
            all_scores=[float(s) for s in scores],
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.KNN.value,
            "contamination": 0.1,
            "n_neighbors": 5,
            "method": "largest",
        }
