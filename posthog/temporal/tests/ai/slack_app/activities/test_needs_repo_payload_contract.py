from temporalio.common import _type_hints_from_func
from temporalio.converter import DataConverter

from posthog.temporal.ai.slack_app.activities.classifiers import classify_posthog_code_task_needs_repo_activity
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs

from products.slack_app.backend.services.slack_messages import SlackThreadMessage

INPUTS = PostHogCodeSlackMentionWorkflowInputs(
    event={"text": "why did signups drop", "ts": "1700000000.000100"},
    integration_id=410,
    slack_team_id="T_WS",
    user_id=7,
)


async def test_a_queued_three_payload_task_still_decodes_its_inputs():
    activity = classify_posthog_code_task_needs_repo_activity
    fn = getattr(activity, "__wrapped__", activity)
    arg_types, _ = _type_hints_from_func(fn)

    converter = DataConverter.default
    payloads = await converter.encode(["why did signups drop", [SlackThreadMessage(user="Ada", text="hi")], INPUTS])

    # Temporal drops the activity's type hints when the declared parameter count differs from
    # the queued payload count, which decodes a dataclass payload as a plain dict and fails on
    # attribute access. A fourth parameter would reintroduce that for every in-flight task.
    hints = arg_types if arg_types is not None and len(arg_types) == len(payloads) else None
    decoded = await converter.decode(payloads, type_hints=hints)

    assert isinstance(decoded[2], PostHogCodeSlackMentionWorkflowInputs)
    assert decoded[2].integration_id == 410
