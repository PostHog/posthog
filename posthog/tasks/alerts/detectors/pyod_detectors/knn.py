from typing import Any

from pyod.models.knn import KNN

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.pyod_detectors.base_pyod import BasePyODDetector
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.KNN)
class KNNDetector(BasePyODDetector):
    """K-nearest neighbors — points far from others are anomalies."""

    def _build_model(self, n_samples: int) -> KNN:
        n_neighbors = min(self.config.get("n_neighbors", 5), n_samples - 1)
        method = self.config.get("method", "largest")
        return KNN(n_neighbors=n_neighbors, method=method)

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {
            "type": DetectorType.KNN.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "n_neighbors": 5,
            "method": "largest",
        }
