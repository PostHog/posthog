from typing import Any

from pyod.models.pca import PCA

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.pyod_detectors.base_pyod import BasePyODDetector
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.PCA)
class PCADetector(BasePyODDetector):
    """PCA-based — detects anomalies via reconstruction error."""

    def _build_model(self, n_samples: int) -> PCA:
        return PCA()

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {"type": DetectorType.PCA.value, "threshold": cls.DEFAULT_THRESHOLD}
