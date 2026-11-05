import json
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from products.ai_observability.backend.facade.limits import AIEventLimits, get_ai_event_limits

VALID = AIEventLimits(
    max_event_bytes_default=12_000_000,
    max_event_bytes_overrides=(24_000_000, 48_000_000),
    max_event_bytes_ceiling=48_000_000,
    included_bytes_per_event=100_000,
    media_offload_min_bytes=15_000,
    text_offload_enabled=False,
    text_offload_min_event_bytes=100_000,
)


def test_file_and_loader_agree() -> None:
    raw = json.loads((Path(__file__).parents[2] / "shared" / "crosslang" / "ai_event_limits.json").read_text())
    get_ai_event_limits.cache_clear()
    try:
        assert dataclasses.asdict(get_ai_event_limits()) == {
            **raw,
            "max_event_bytes_overrides": tuple(raw["max_event_bytes_overrides"]),
        }
    finally:
        get_ai_event_limits.cache_clear()


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"max_event_bytes_default": 12e6}, "max_event_bytes_default must be a positive integer"),
        ({"max_event_bytes_default": True}, "max_event_bytes_default must be a positive integer"),
        ({"media_offload_min_bytes": 0}, "media_offload_min_bytes must be a positive integer"),
        ({"max_event_bytes_overrides": (48_000_000, 24_000_000)}, "each override must be larger"),
        ({"max_event_bytes_overrides": (12_000_000, 48_000_000)}, "each override must be larger"),
        ({"max_event_bytes_ceiling": 24_000_000}, "no cap may exceed max_event_bytes_ceiling"),
        ({"included_bytes_per_event": 12_000_000}, "included_bytes_per_event must be smaller"),
        ({"text_offload_enabled": "false"}, "text_offload_enabled must be a boolean"),
    ],
)
def test_rejects_limits_that_contradict_each_other(changes: dict[str, Any], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        dataclasses.replace(VALID, **changes)
