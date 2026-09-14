import json

import pytest
from unittest.mock import patch

from posthog.cdp.workflow_step_resume import RESULT_BYTE_CAP, RESULT_STRING_CAP, emit_workflow_step_resume

_PRODUCE = "posthog.cdp.workflow_step_resume.produce_internal_event"


def test_emits_the_wake_keyed_to_the_step_with_capped_strings() -> None:
    with patch(_PRODUCE) as produce:
        emit_workflow_step_resume(
            team_id=7,
            origin_key="job:step:3",
            status="completed",
            result={"final_message": "x" * (RESULT_STRING_CAP + 1), "pr_urls": ["u"], "error_message": None},
        )

    produce.assert_called_once()
    assert produce.call_args.kwargs["team_id"] == 7
    event = produce.call_args.kwargs["event"]
    assert event.event == "$workflow_step_resume"
    assert event.distinct_id == "team_7"
    assert event.properties == {
        "origin_key": "job:step:3",
        "status": "completed",
        "result": {"final_message": "x" * RESULT_STRING_CAP, "pr_urls": ["u"]},
    }


def test_a_failed_emit_does_not_raise() -> None:
    with patch(_PRODUCE, side_effect=RuntimeError("kafka down")):
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="failed")


@pytest.mark.parametrize(
    "result",
    [
        {"final_message": "😀" * 1500},
        {"final_message": "漢" * 1500, "error_message": "字" * 1500},
        {"pr_urls": [f"https://example.com/pr/{index}" for index in range(1000)]},
        {"nested": {"text": '\\"\n' * 1500}, "pr_urls": ["https://example.com/" + "x" * 6000]},
    ],
)
def test_result_fits_the_serialized_byte_budget(result) -> None:
    with patch(_PRODUCE) as produce:
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="completed", result=result)

    capped = produce.call_args.kwargs["event"].properties["result"]
    assert len(json.dumps(capped, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= RESULT_BYTE_CAP
    assert all(url in result["pr_urls"] for url in capped.get("pr_urls", []))


def test_delivery_activities_can_retry_a_failed_emit() -> None:
    with patch(_PRODUCE, side_effect=RuntimeError("kafka down")), pytest.raises(RuntimeError, match="kafka down"):
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="failed", raise_on_error=True)
