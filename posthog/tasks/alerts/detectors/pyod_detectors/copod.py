from typing import Any

from pyod.models.copod import COPOD

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.pyod_detectors.base_pyod import BasePyODDetector
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.COPOD)
class COPODDetector(BasePyODDetector):
    """Copula-based outlier detection — efficient and parameter-free."""

    def _build_model(self, n_samples: int) -> COPOD:
        return COPOD()

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {"type": DetectorType.COPOD.value, "threshold": cls.DEFAULT_THRESHOLD}
