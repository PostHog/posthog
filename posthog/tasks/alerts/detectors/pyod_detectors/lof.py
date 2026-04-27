from typing import Any

from pyod.models.lof import LOF

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.pyod_detectors.base_pyod import BasePyODDetector
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.LOF)
class LOFDetector(BasePyODDetector):
    """Local outlier factor — density-based, good for seasonal data."""

    MIN_SAMPLES = 20

    def _build_model(self, n_samples: int) -> LOF:
        n_neighbors = min(self.config.get("n_neighbors", 20), n_samples - 1)
        return LOF(n_neighbors=n_neighbors, novelty=True)

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {"type": DetectorType.LOF.value, "threshold": cls.DEFAULT_THRESHOLD, "n_neighbors": 20}
