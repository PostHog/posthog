import pytest

from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs, coerce_mention_workflow_inputs


def test_coerce_returns_dataclass_unchanged():
    inputs = PostHogCodeSlackMentionWorkflowInputs(event={"ts": "1.2"}, integration_id=7, slack_team_id="T1")
    assert coerce_mention_workflow_inputs(inputs) is inputs


def test_coerce_rebuilds_dataclass_from_dict():
    # A rolling deploy can deliver the payload as a raw dict; reading
    # ``.integration_id`` on it used to raise an opaque AttributeError.
    coerced = coerce_mention_workflow_inputs(
        {"event": {"ts": "1.2"}, "integration_id": 7, "slack_team_id": "T1", "user_id": 42}
    )
    assert isinstance(coerced, PostHogCodeSlackMentionWorkflowInputs)
    assert coerced.integration_id == 7
    assert coerced.slack_team_id == "T1"
    assert coerced.user_id == 42


def test_coerce_drops_unknown_keys_from_dict():
    # A newer sender's extra field must not blow up an older activity mid-deploy.
    coerced = coerce_mention_workflow_inputs(
        {"event": {}, "integration_id": 1, "slack_team_id": "T1", "some_future_field": "x"}
    )
    assert coerced.integration_id == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"integration_id": 1, "slack_team_id": "T1"},  # missing required ``event``
        {"event": {}},  # missing required ``integration_id`` / ``slack_team_id``
    ],
)
def test_coerce_raises_with_context_when_required_fields_missing(payload):
    with pytest.raises(TypeError, match="PostHogCodeSlackMentionWorkflowInputs"):
        coerce_mention_workflow_inputs(payload)


def test_coerce_raises_on_unexpected_type():
    with pytest.raises(TypeError, match="Unexpected activity inputs type"):
        coerce_mention_workflow_inputs("not-a-dict")
