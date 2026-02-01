from typing import Any

from posthog.tasks.alerts.detectors.base import BaseDetector
from posthog.tasks.alerts.detectors.statistical.zscore import ZScoreDetector

DETECTOR_REGISTRY: dict[str, type[BaseDetector]] = {
    "zscore": ZScoreDetector,
}


def get_detector(config: dict[str, Any]) -> BaseDetector:
    """
    Create a detector instance from configuration.

    Args:
        config: Detector configuration dict with 'type' key

    Returns:
        Configured detector instance

    Raises:
        ValueError: If detector type is unknown
    """
    detector_type = config.get("type")
    if not detector_type:
        raise ValueError("Detector config must have a 'type' field")

    detector_class = DETECTOR_REGISTRY.get(detector_type)
    if not detector_class:
        raise ValueError(f"Unknown detector type: {detector_type}. Available: {list(DETECTOR_REGISTRY.keys())}")

    return detector_class(config)
