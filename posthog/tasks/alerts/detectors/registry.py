import logging
from typing import TYPE_CHECKING, Any

from posthog.schema import DetectorType

if TYPE_CHECKING:
    from posthog.tasks.alerts.detectors.base import BaseDetector

logger = logging.getLogger(__name__)

_DETECTOR_REGISTRY: dict[str, type["BaseDetector"]] = {}


def register_detector(detector_type: str | DetectorType):
    """Decorator to register a detector class."""

    def decorator(cls: type["BaseDetector"]):
        key = detector_type.value if isinstance(detector_type, DetectorType) else detector_type
        _DETECTOR_REGISTRY[key] = cls
        return cls

    return decorator


def get_detector(config: dict[str, Any]) -> "BaseDetector":
    """
    Factory function to create detector from config.

    Args:
        config: Detector configuration dict with 'type' key

    Returns:
        Instantiated detector

    Raises:
        ValueError: If detector type is unknown
    """
    # Ensure all detectors are registered
    _ensure_registered()

    detector_type = config.get("type")
    if not detector_type:
        raise ValueError("Detector config must have a 'type' field")

    if detector_type not in _DETECTOR_REGISTRY:
        raise ValueError(f"Unknown detector type: {detector_type}. Available: {list(_DETECTOR_REGISTRY.keys())}")

    detector_cls = _DETECTOR_REGISTRY[detector_type]
    return detector_cls(config)


def get_available_detectors() -> list[str]:
    """Return list of registered detector types."""
    _ensure_registered()
    return list(_DETECTOR_REGISTRY.keys())


_REGISTERED = False


def _ensure_registered():
    """Ensure all detector modules are imported and registered."""
    global _REGISTERED
    if _REGISTERED:
        return

    # Import all detector modules to trigger registration
    # Statistical detectors (no external dependencies)
    from posthog.tasks.alerts.detectors import threshold  # noqa: F401
    from posthog.tasks.alerts.detectors.statistical import iqr, mad, zscore  # noqa: F401

    # PyOD detectors (optional - require pyod package)
    try:
        from posthog.tasks.alerts.detectors.pyod_detectors import copod, ecod, isolation_forest, knn  # noqa: F401
    except ImportError:
        logger.warning("PyOD not installed - ML-based detectors (ECOD, COPOD, IsolationForest, KNN) unavailable")

    _REGISTERED = True
