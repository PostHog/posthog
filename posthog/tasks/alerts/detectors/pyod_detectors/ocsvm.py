from typing import Any

from pyod.models.ocsvm import OCSVM

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.pyod_detectors.base_pyod import BasePyODDetector
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.OCSVM)
class OCSVMDetector(BasePyODDetector):
    """One-class SVM — learns a boundary around normal data."""

    def _build_model(self, n_samples: int) -> OCSVM:
        return OCSVM(
            kernel=self.config.get("kernel", "rbf"),
            nu=self.config.get("nu", 0.1),
        )

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {"type": DetectorType.OCSVM.value, "threshold": cls.DEFAULT_THRESHOLD, "kernel": "rbf", "nu": 0.1}
