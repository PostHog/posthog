import pytest
from unittest.mock import patch

from posthog.temporal.ai.slack_app import posthog_code_slack_mention
from posthog.temporal.ai.slack_app.helpers import process_mention_message
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,patched,expect_classifier",
    [
        # File-only replies skip the classifier so the attachment isn't dropped.
        ("", True, False),
        # Replies with text still face the classifier even when files are attached.
        ("nice weather today", True, True),
        # Replays of histories recorded before the patch keep the old always-classify sequence.
        ("", False, True),
    ],
)
async def test_untagged_followup_with_files_classifier_gating(
    text: str, patched: bool, expect_classifier: bool
) -> None:
    workflow = posthog_code_slack_mention.PostHogCodeSlackMentionWorkflow()
    calls: list[str] = []
    inputs = PostHogCodeSlackMentionWorkflowInputs(
        event={
            "channel": "C123",
            "ts": "1234.5679",
            "user": "U_ALICE",
            "text": text,
            "files": [{"id": "F123", "name": "debug.log"}],
        },
        integration_id=1,
        slack_team_id="T_SLACK",
        user_id=42,
        untagged_followup=True,
    )

    async def fake_execute_activity(activity_fn, *args):
        calls.append(activity_fn.__name__)
        if activity_fn is process_mention_message.enforce_posthog_code_billing_quota_activity:
            return False
        if activity_fn is process_mention_message.classify_untagged_followup_activity:
            return True
        if activity_fn is process_mention_message.forward_posthog_code_followup_activity:
            return True

        raise AssertionError(f"unexpected activity: {activity_fn.__name__}")

    with (
        patch.object(process_mention_message.workflow, "patched", return_value=patched),
        patch.object(process_mention_message, "_execute_posthog_code_activity", side_effect=fake_execute_activity),
    ):
        await workflow.run(inputs)

    expected = ["enforce_posthog_code_billing_quota_activity"]
    if expect_classifier:
        expected.append("classify_untagged_followup_activity")
    expected.append("forward_posthog_code_followup_activity")
    assert calls == expected
