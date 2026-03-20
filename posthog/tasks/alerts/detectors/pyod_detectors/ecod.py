from typing import Any

from pyod.models.ecod import ECOD

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.pyod_detectors.base_pyod import BasePyODDetector
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.ECOD)
class ECODDetector(BasePyODDetector):
    """Empirical Cumulative Distribution (ECOD) — parameter-free and interpretable."""

    def _build_model(self, n_samples: int) -> ECOD:
        return ECOD()

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {"type": DetectorType.ECOD.value, "threshold": 0.9}
