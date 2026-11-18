import json
from pathlib import Path

import pytest

from ee.hogai.sandbox.types import (
    is_idle_resume_turn_complete,
    is_turn_complete,
    pi_turn_error,
    turn_completed_successfully,
)


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        pytest.param(case["event"], case["expect"], id=case["name"])
        for case in json.loads(Path(__file__).with_name("turn_event_contract.json").read_text())
    ],
)
def test_turn_event_contract(event: dict[str, object], expected: dict[str, bool]) -> None:
    assert {
        "turn_complete": is_turn_complete(event),
        "idle_resume": is_idle_resume_turn_complete(event),
        "pi_error": pi_turn_error(event),
        "successful": turn_completed_successfully(event),
    } == {key: expected[key] for key in ("turn_complete", "idle_resume", "pi_error", "successful")}
