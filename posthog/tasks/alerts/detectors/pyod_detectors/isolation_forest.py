from typing import Any

from pyod.models.iforest import IForest

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.pyod_detectors.base_pyod import BasePyODDetector
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.ISOLATION_FOREST)
class IsolationForestDetector(BasePyODDetector):
    """Isolation Forest — isolates anomalies using random trees."""

    def _build_model(self, n_samples: int) -> IForest:
        return IForest(
            n_estimators=self.config.get("n_estimators", 100),
            random_state=42,
        )

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {"type": DetectorType.ISOLATION_FOREST.value, "threshold": 0.9, "n_estimators": 100}
