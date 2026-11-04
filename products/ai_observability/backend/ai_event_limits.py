import json
from functools import lru_cache
from pathlib import Path

from posthog.dataclasses import frozen

_LIMITS_PATH = Path(__file__).parents[1] / "shared" / "crosslang" / "ai_event_limits.json"


@frozen
class AIEventLimits:
    """The size limits for AI events, in decimal bytes. `shared/crosslang/README.md` describes each field."""

    max_event_bytes_default: int
    max_event_bytes_overrides: tuple[int, ...]
    max_event_bytes_ceiling: int
    included_bytes_per_event: int
    media_offload_min_bytes: int
    text_offload_enabled: bool
    text_offload_min_event_bytes: int

    def __post_init__(self) -> None:
        sizes = {
            "max_event_bytes_default": self.max_event_bytes_default,
            "max_event_bytes_ceiling": self.max_event_bytes_ceiling,
            "included_bytes_per_event": self.included_bytes_per_event,
            "media_offload_min_bytes": self.media_offload_min_bytes,
            "text_offload_min_event_bytes": self.text_offload_min_event_bytes,
            **{f"max_event_bytes_overrides[{i}]": size for i, size in enumerate(self.max_event_bytes_overrides)},
        }
        for name, size in sizes.items():
            # bool is an int subclass, and a float such as 12e6 parses from JSON, so check the exact type.
            if type(size) is not int or size <= 0:
                raise ValueError(f"{name} must be a positive integer of bytes, got {size!r}")
        caps = (self.max_event_bytes_default, *self.max_event_bytes_overrides)
        if any(larger <= smaller for smaller, larger in zip(caps, caps[1:])):
            raise ValueError(f"each override must be larger than the default and the override before it, got {caps}")
        if caps[-1] > self.max_event_bytes_ceiling:
            raise ValueError(f"no cap may exceed max_event_bytes_ceiling ({self.max_event_bytes_ceiling}), got {caps}")
        if self.included_bytes_per_event >= self.max_event_bytes_default:
            raise ValueError("included_bytes_per_event must be smaller than max_event_bytes_default")


@lru_cache(maxsize=1)
def get_ai_event_limits() -> AIEventLimits:
    """Read the limits once.

    A missing or invalid file raises instead of falling back to a guess, because these values decide what a
    customer is billed and what capture accepts.
    """
    raw = json.loads(_LIMITS_PATH.read_text())
    return AIEventLimits(**{**raw, "max_event_bytes_overrides": tuple(raw["max_event_bytes_overrides"])})
