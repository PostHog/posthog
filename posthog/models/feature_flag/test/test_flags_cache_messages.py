import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pydantic import ValidationError

from posthog.models.feature_flag.flags_cache_messages import FlagsCacheInvalidation

# 4 levels up: test/ -> feature_flag/ -> models/ -> posthog/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_PATH = _REPO_ROOT / "rust" / "feature-flags" / "tests" / "fixtures" / "flags_cache_invalidation_v1.json"


def test_fixture_exists() -> None:
    assert FIXTURE_PATH.exists(), (
        f"Contract fixture missing at {FIXTURE_PATH}. "
        f"Both Python and Rust round-trip tests read this file; if it moves, both fail."
    )


def test_fixture_round_trip() -> None:
    raw = FIXTURE_PATH.read_text()

    parsed = FlagsCacheInvalidation.model_validate_json(raw)
    assert parsed.version == 1
    assert parsed.team_id == 12345
    assert parsed.operation == "invalidate"
    assert parsed.emitted_at == datetime(2026, 4, 23, 10, 37, 0, tzinfo=UTC)

    # Reserialize and reparse — proves the schema survives a full round-trip even
    # when Pydantic's datetime output (`+00:00`) differs from the fixture's `Z`.
    reparsed = FlagsCacheInvalidation.model_validate_json(parsed.model_dump_json())
    assert reparsed == parsed


def test_rejects_unknown_version() -> None:
    payload = json.dumps(
        {
            "version": 2,
            "team_id": 12345,
            "operation": "invalidate",
            "emitted_at": "2026-04-23T10:37:00Z",
        }
    )
    with pytest.raises(ValidationError):
        FlagsCacheInvalidation.model_validate_json(payload)


def test_rejects_unknown_operation() -> None:
    payload = json.dumps(
        {
            "version": 1,
            "team_id": 12345,
            "operation": "clear",
            "emitted_at": "2026-04-23T10:37:00Z",
        }
    )
    with pytest.raises(ValidationError):
        FlagsCacheInvalidation.model_validate_json(payload)
