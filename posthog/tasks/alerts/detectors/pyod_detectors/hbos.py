from typing import Any

from pyod.models.hbos import HBOS

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.pyod_detectors.base_pyod import BasePyODDetector
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.HBOS)
class HBOSDetector(BasePyODDetector):
    """Histogram-based outlier score — very fast, good for high-volume alerting."""

    def _build_model(self, n_samples: int) -> HBOS:
        return HBOS(n_bins=self.config.get("n_bins", 10))

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {"type": DetectorType.HBOS.value, "threshold": 0.9, "n_bins": 10}
