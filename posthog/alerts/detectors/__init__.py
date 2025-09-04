"""
Alert Detectors - Modular anomaly detection system for PostHog alerts.

Provides flexible detection of anomalies and thresholds in time series data.
Each detector type is implemented in its own module for better maintainability.
"""

from .base import BaseDetector, DetectionDirection, DetectionResult, DetectorType, ValueType
from .factory import create_detector
from .mad import MADDetector
from .threshold import ThresholdDetector
from .zscore import ZScoreDetector

__all__ = [
    # Base classes and types
    "BaseDetector",
    "DetectionResult",
    "DetectorType",
    "DetectionDirection",
    "ValueType",
    # Factory function
    "create_detector",
    # Detector implementations
    "ThresholdDetector",
    "ZScoreDetector",
    "MADDetector",
]
