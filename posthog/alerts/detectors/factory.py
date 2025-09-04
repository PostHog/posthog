"""Factory function for creating detector instances."""

from typing import Any

from .base import BaseDetector, DetectorType
from .mad import MADDetector
from .threshold import ThresholdDetector
from .zscore import ZScoreDetector


def create_detector(detector_type: DetectorType, config: dict[str, Any]) -> BaseDetector:
    """
    Factory function to create detector instances.

    Args:
        detector_type: Type of detector to create
        config: Configuration dictionary for the detector

    Returns:
        Configured detector instance

    Raises:
        ValueError: If detector_type is unknown
    """
    detector_classes = {
        DetectorType.THRESHOLD: ThresholdDetector,
        DetectorType.ZSCORE: ZScoreDetector,
        DetectorType.MAD: MADDetector,
    }

    detector_class = detector_classes.get(detector_type)
    if not detector_class:
        raise ValueError(f"Unknown detector type: {detector_type}")

    return detector_class(config)
