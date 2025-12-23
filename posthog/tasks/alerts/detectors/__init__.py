from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.ensemble import EnsembleDetector
from posthog.tasks.alerts.detectors.pyod_detectors import (
    COPODDetector,
    ECODDetector,
    IsolationForestDetector,
    KNNDetector,
)
from posthog.tasks.alerts.detectors.registry import get_available_detectors, get_detector
from posthog.tasks.alerts.detectors.statistical import IQRDetector, MADDetector, ZScoreDetector

# Import all detectors to trigger registration
from posthog.tasks.alerts.detectors.threshold import ThresholdDetector

__all__ = [
    "BaseDetector",
    "DetectionResult",
    "get_detector",
    "get_available_detectors",
    # Concrete detectors
    "ThresholdDetector",
    "ZScoreDetector",
    "MADDetector",
    "IQRDetector",
    "IsolationForestDetector",
    "ECODDetector",
    "COPODDetector",
    "KNNDetector",
    "EnsembleDetector",
]
