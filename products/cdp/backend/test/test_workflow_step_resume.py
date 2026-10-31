import json

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import override_settings

import jwt
import requests

from products.cdp.backend.workflow_step_resume import (
    RESULT_BYTE_CAP,
    RESULT_STRING_CAP,
    WorkflowStepResumeNotTaken,
    emit_workflow_step_resume,
)

_PRODUCE = "products.cdp.backend.workflow_step_resume.produce_internal_event"
_POST = "posthog.plugins.plugin_server_api.internal_requests.post"


def _response(status_code: int) -> MagicMock:
    response = MagicMock(status_code=status_code)
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code}", response=response)
    return response


def test_posts_the_wake_with_a_scoped_jwt_and_capped_strings() -> None:
    with patch(_POST, return_value=_response(200)) as post, patch(_PRODUCE) as produce:
        emit_workflow_step_resume(
            team_id=7,
            origin_key="job:step:3",
            status="completed",
            result={"final_message": "x" * (RESULT_STRING_CAP + 1), "pr_urls": ["u"], "error_message": None},
        )

    produce.assert_not_called()
    kwargs = post.call_args.kwargs
    assert post.call_args.args[0].endswith("/api/projects/7/workflow_steps/resume")
    assert kwargs["json"] == {
        "origin_key": "job:step:3",
        "status": "completed",
        "result": {"final_message": "x" * RESULT_STRING_CAP, "pr_urls": ["u"], "error_message": None},
    }
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


def test_emits_the_internal_event_until_the_key_is_provisioned() -> None:
    with (
        override_settings(WORKFLOWS_STEP_RESUME_JWT_SECRETS=[]),
        patch(_POST) as post,
        patch(_PRODUCE) as produce,
    ):
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="completed", result={"pr_urls": ["u"]})

    post.assert_not_called()
    produce.assert_called_once()
    assert produce.call_args.kwargs["team_id"] == 7
    event = produce.call_args.kwargs["event"]
    assert event.event == "$workflow_step_resume"
    assert event.distinct_id == "team_7"
    assert event.properties == {"origin_key": "job:step:3", "status": "completed", "result": {"pr_urls": ["u"]}}


@pytest.mark.parametrize("failure", [_response(503), requests.ConnectionError("api down")])
def test_the_wake_falls_back_to_the_internal_event_when_the_api_cannot_take_it(failure) -> None:
    post_kwargs = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
    with patch(_POST, **post_kwargs), patch(_PRODUCE) as produce:
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="completed", result={"pr_urls": ["u"]})

    produce.assert_called_once()
    event = produce.call_args.kwargs["event"]
    assert event.event == "$workflow_step_resume"
    assert event.properties == {"origin_key": "job:step:3", "status": "completed", "result": {"pr_urls": ["u"]}}


def _outcome(outcome: str) -> MagicMock:
    response = _response(200)
    response.json.return_value = {"outcome": outcome}
    return response


@pytest.mark.parametrize(
    "responses,raise_on_error,attempts,taken",
    [
        ([_response(409), _outcome("delivered")], False, 2, True),
        ([_outcome("stale_key")], False, 1, True),
        ([_outcome("job_missing")], False, 1, True),
        ([_response(409)] * 4, False, 4, True),
        # A caller that retries on its own schedule gets no sleeps here, and learns the wake was not taken.
        ([_response(409)], True, 1, False),
    ],
)
def test_only_a_step_the_worker_still_holds_gets_a_short_retry(responses, raise_on_error, attempts, taken) -> None:
    with (
        patch(_POST, side_effect=responses) as post,
        patch("products.cdp.backend.workflow_step_resume.time.sleep") as sleep,
        patch(_PRODUCE) as produce,
    ):
        if taken:
            emit_workflow_step_resume(
                team_id=7, origin_key="job:step:3", status="completed", raise_on_error=raise_on_error
            )
        else:
            with pytest.raises(WorkflowStepResumeNotTaken):
                emit_workflow_step_resume(
                    team_id=7, origin_key="job:step:3", status="completed", raise_on_error=raise_on_error
                )

    assert post.call_count == attempts
    assert sleep.call_count == attempts - 1
    produce.assert_not_called()


def test_an_undelivered_fallback_event_raises_for_a_caller_that_retries() -> None:
    undelivered = MagicMock()
    undelivered.done.return_value = False
    with (
        override_settings(WORKFLOWS_STEP_RESUME_JWT_SECRETS=[]),
        patch(_PRODUCE, return_value=undelivered),
        patch("products.cdp.backend.workflow_step_resume.flush_internal_events_producer"),
        pytest.raises(WorkflowStepResumeNotTaken),
    ):
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="completed", raise_on_error=True)


def test_a_failed_emit_does_not_raise() -> None:
    with (
        patch(_POST, side_effect=requests.ConnectionError("api down")),
        patch(_PRODUCE, side_effect=RuntimeError("kafka down")),
    ):
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="failed")


@pytest.mark.parametrize(
    "result",
    [
        {"final_message": "😀" * 1500},
        {"final_message": "漢" * 1500, "error_message": "字" * 1500},
        {"pr_urls": [f"https://example.com/pr/{index}" for index in range(1000)]},
        {"nested": {"text": '\\"\n' * 1500}, "pr_urls": ["https://example.com/" + "x" * 6000]},
        {"a": "x" * 1500, "b": "y" * 1500, "c": "z" * 1066, "d": None},
    ],
)
def test_result_fits_the_serialized_byte_budget(result) -> None:
    with patch(_POST, return_value=_response(200)) as post:
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="completed", result=result)

    capped = post.call_args.kwargs["json"]["result"]
    assert len(json.dumps(capped, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= RESULT_BYTE_CAP
    assert all(url in result["pr_urls"] for url in capped.get("pr_urls", []))


def test_delivery_activities_can_retry_a_failed_emit() -> None:
    with (
        patch(_POST, side_effect=requests.ConnectionError("api down")),
        patch(_PRODUCE, side_effect=RuntimeError("kafka down")),
        pytest.raises(RuntimeError, match="kafka down"),
    ):
        emit_workflow_step_resume(team_id=7, origin_key="job:step:3", status="failed", raise_on_error=True)
