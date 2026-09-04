from typing import Any

import pytest

from temporalio.converter import DataConverter

from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs, coerce_mention_workflow_inputs

from products.slack_app.backend.services.slack_messages import SlackFileRef, SlackThreadMessage, encode_slack_file_refs


def test_coerce_returns_dataclass_unchanged():
    inputs = PostHogCodeSlackMentionWorkflowInputs(
        event={"ts": "1.2"}, integration_id=7, slack_team_id="T1", user_id=42
    )
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
        {"event": {}, "integration_id": 1, "slack_team_id": "T1", "user_id": 42, "some_future_field": "x"}
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


def _round_trip(value: object, hint: type) -> Any:
    converter = DataConverter.default.payload_converter
    return converter.from_payloads(converter.to_payloads([value]), [hint])[0]


def test_thread_snapshot_survives_the_temporal_payload_boundary():
    messages = [
        SlackThreadMessage(
            user="mira",
            user_id="U_MIRA",
            text="",
            ts="1.0",
            files_json=encode_slack_file_refs([SlackFileRef(id="F1", size=9)]),
        ),
        SlackThreadMessage(user="mira", user_id="U_MIRA", text="what is this", ts="2.0"),
    ]
    round_tripped = _round_trip(messages, list[SlackThreadMessage])
    assert round_tripped == messages
    assert round_tripped[0].files == [SlackFileRef(id="F1", size=9)]


def test_thread_snapshot_with_attachments_decodes_under_the_previous_builds_type():
    # A worker on the previous build reads this activity result and these activity
    # arguments as ``list[dict[str, str]]``. Temporal rejects the whole message when any
    # value is not a string, so attachments have to travel as a string. Carrying them as
    # a list here would fail every in-flight mention for the length of a rolling deploy.
    messages = [
        SlackThreadMessage(
            user="mira",
            user_id="U_MIRA",
            text="what is this",
            ts="1.0",
            files_json=encode_slack_file_refs([SlackFileRef(id="F1", name="trace.png", size=9)]),
        )
    ]
    assert _round_trip(messages, list[dict[str, str]]) == [
        {
            "user": "mira",
            "user_id": "U_MIRA",
            "text": "what is this",
            "ts": "1.0",
            "files_json": encode_slack_file_refs([SlackFileRef(id="F1", name="trace.png", size=9)]),
        }
    ]


def test_thread_message_reads_back_no_attachments_from_unusable_json():
    # ``files_json`` crosses a version boundary, so a value the current build cannot parse
    # is reachable. Reporting no attachments keeps the message and its text usable.
    assert SlackThreadMessage(user="mira", files_json="not json").files == []


def test_thread_snapshot_recorded_before_a_field_existed_still_decodes():
    # The snapshot is an activity result, so a rolling deploy replays histories written
    # by the previous build against the current type. A field added without a default
    # would fail that decode and wedge every in-flight mention.
    recorded = [{"user": "mira", "user_id": "U_MIRA", "text": "hi", "ts": "1.0"}]
    assert _round_trip(recorded, list[SlackThreadMessage]) == [
        SlackThreadMessage(user="mira", user_id="U_MIRA", text="hi", ts="1.0")
    ]
