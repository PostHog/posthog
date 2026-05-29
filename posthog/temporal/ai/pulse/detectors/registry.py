from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.temporal.ai.pulse.detectors.base import PulseDetector

_DETECTOR_REGISTRY: dict[str, type["PulseDetector"]] = {}


def register_detector(detection_mode: str):
    def decorator(cls: type["PulseDetector"]) -> type["PulseDetector"]:
        _DETECTOR_REGISTRY[detection_mode] = cls
        return cls

    return decorator


_REGISTERED = False


def _ensure_registered() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    # change_v1 registers itself on import.
    from posthog.temporal.ai.pulse import detection  # noqa: F401

    _REGISTERED = True


def get_detector(detection_mode: str) -> "PulseDetector":
    _ensure_registered()
    detector_cls = _DETECTOR_REGISTRY.get(detection_mode)
    if detector_cls is None:
        raise ValueError(f"Unknown detection mode: {detection_mode}. Available: {sorted(_DETECTOR_REGISTRY)}")
    return detector_cls()
