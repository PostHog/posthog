import json

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import override_settings

import jwt
import requests

from posthog.cdp.workflow_step_resume import (
    RESULT_BYTE_CAP,
    RESULT_STRING_CAP,
    STEP_RESUME_DELIVERY_TASK,
    deliver_workflow_step_resume,
    emit_workflow_step_resume,
)

_PRODUCE = "posthog.cdp.workflow_step_resume.produce_internal_event"
_SEND_TASK = "posthog.cdp.workflow_step_resume.current_app.send_task"
_POST = "posthog.plugins.plugin_server_api.internal_requests.post"


def test_queues_the_wake_keyed_to_the_step_with_capped_strings() -> None:
    with patch(_SEND_TASK) as send_task, patch(_PRODUCE) as produce:
        emit_workflow_step_resume(
            team_id=7,
            origin_key="job:step:3",
            status="completed",
            result={"final_message": "x" * (RESULT_STRING_CAP + 1), "pr_urls": ["u"], "error_message": None},
        )

    produce.assert_not_called()
    send_task.assert_called_once_with(
        STEP_RESUME_DELIVERY_TASK,
        kwargs={
            "team_id": 7,
            "origin_key": "job:step:3",
            "status": "completed",
            "result": {"final_message": "x" * RESULT_STRING_CAP, "pr_urls": ["u"]},
        },
    )


def test_emits_the_internal_event_until_the_key_is_provisioned() -> None:
    with (
        override_settings(WORKFLOWS_STEP_RESUME_JWT_SECRETS=[]),
        patch(_SEND_TASK) as send_task,
        patch(_PRODUCE) as produce,
    ):
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="completed", result={"pr_urls": ["u"]})

    send_task.assert_not_called()
    produce.assert_called_once()
    assert produce.call_args.kwargs["team_id"] == 7
    event = produce.call_args.kwargs["event"]
    assert event.event == "$workflow_step_resume"
    assert event.distinct_id == "team_7"
    assert event.properties == {"origin_key": "job:step:3", "status": "completed", "result": {"pr_urls": ["u"]}}


def test_a_failed_emit_does_not_raise() -> None:
    with patch(_SEND_TASK, side_effect=RuntimeError("broker down")):
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
    with patch(_SEND_TASK) as send_task:
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="completed", result=result)

    capped = send_task.call_args.kwargs["kwargs"]["result"]
    assert len(json.dumps(capped, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= RESULT_BYTE_CAP
    assert all(url in result["pr_urls"] for url in capped.get("pr_urls", []))


def test_delivery_activities_can_retry_a_failed_emit() -> None:
    with (
        patch(_SEND_TASK, side_effect=RuntimeError("broker down")),
        pytest.raises(RuntimeError, match="broker down"),
    ):
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="failed", raise_on_error=True)


def _response(status_code: int) -> MagicMock:
    response = MagicMock(status_code=status_code)
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code}", response=response)
    return response


def test_the_delivery_task_posts_the_wake_with_a_scoped_jwt() -> None:
    with patch(_POST, return_value=_response(200)) as post:
        deliver_workflow_step_resume(team_id=7, origin_key="job:step:3", status="completed", result={"a": 1})

    kwargs = post.call_args.kwargs
    assert post.call_args.args[0].endswith("/api/projects/7/workflow_steps/resume")
    assert kwargs["json"] == {"origin_key": "job:step:3", "status": "completed", "result": {"a": 1}}
    assert kwargs["timeout"] == 10
    assert "x-internal-api-secret" not in {key.lower() for key in kwargs["headers"]}
    claims = jwt.decode(
        kwargs["headers"]["Authorization"].removeprefix("Bearer "),
        settings.WORKFLOWS_STEP_RESUME_JWT_SECRETS[0],
        audience="posthog:workflows:step_resume",
        algorithms=["HS256"],
    )
    assert claims["team_id"] == 7
    assert claims["origin_key"] == "job:step:3"


@pytest.mark.parametrize("status_code", [409, 503])
def test_the_delivery_task_raises_so_celery_retries_when(status_code: int) -> None:
    with patch(_POST, return_value=_response(status_code)), pytest.raises(requests.HTTPError):
        deliver_workflow_step_resume(team_id=7, origin_key="job:step:3", status="completed", result={})
