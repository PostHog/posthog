import dataclasses
from typing import Any

import pytest

from products.ai_observability.backend.ai_event_limits import AIEventLimits, get_ai_event_limits

VALID = AIEventLimits(
    max_event_bytes_default=12_000_000,
    max_event_bytes_overrides=(24_000_000, 48_000_000),
    max_event_bytes_ceiling=48_000_000,
    included_bytes_per_event=100_000,
    media_offload_min_bytes=15_000,
    text_offload_enabled=False,
    text_offload_min_event_bytes=100_000,
)


def test_the_shipped_file_holds_its_invariants() -> None:
    get_ai_event_limits.cache_clear()
    try:
        assert get_ai_event_limits().max_event_bytes_ceiling > 0
    finally:
        get_ai_event_limits.cache_clear()


@pytest.mark.parametrize(
    "changes",
    [
        {"max_event_bytes_default": 12e6},
        {"max_event_bytes_default": True},
        {"media_offload_min_bytes": 0},
        {"max_event_bytes_overrides": (48_000_000, 24_000_000)},
        {"max_event_bytes_overrides": (12_000_000, 48_000_000)},
        {"max_event_bytes_ceiling": 24_000_000},
        {"included_bytes_per_event": 12_000_000},
    ],
)
def test_rejects_limits_that_contradict_each_other(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(VALID, **changes)
