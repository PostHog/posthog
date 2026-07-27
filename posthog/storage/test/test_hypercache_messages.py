import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from django.conf import settings

from pydantic import ValidationError

from posthog.storage.hypercache_messages import HypercacheReadySignal

# The producer round-trips against this fixture strictly; the Rust gateway consumer
# parses the same file leniently. If it moves, both sides fail.
FIXTURE_PATH = Path(settings.BASE_DIR) / "rust" / "feature-flags" / "tests" / "fixtures" / "hypercache_ready_v1.json"


def test_fixture_round_trip() -> None:
    raw = FIXTURE_PATH.read_text()

    parsed = HypercacheReadySignal.model_validate_json(raw)
    assert parsed.v == 1
    assert parsed.team_id == 123
    assert parsed.namespace == "feature_flags"
    assert parsed.value == "flags.json"
    assert parsed.etag == "0123456789abcdef"
    assert parsed.written_at == datetime(2026, 7, 26, 12, 0, 0, 123456, tzinfo=UTC)

    # The fixture must show exactly what the producer emits, field values included —
    # the datetime shape (microseconds + Z) is part of the cross-language contract.
    assert json.loads(parsed.model_dump_json()) == json.loads(raw)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"v": 2}, id="rejects_unknown_version"),
        pytest.param({"written_at": "2026-07-26T12:00:00"}, id="rejects_naive_datetime"),
        pytest.param({"unknown_field": "oops"}, id="rejects_extra_field"),
    ],
)
def test_rejects_invalid_payload(overrides: dict) -> None:
    base = {
        "v": 1,
        "team_id": 123,
        "namespace": "feature_flags",
        "value": "flags.json",
        "etag": "0123456789abcdef",
        "written_at": "2026-07-26T12:00:00Z",
    }
    with pytest.raises(ValidationError):
        HypercacheReadySignal.model_validate_json(json.dumps({**base, **overrides}))
