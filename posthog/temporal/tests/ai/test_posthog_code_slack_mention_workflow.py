import pytest
from unittest.mock import patch

from posthog.temporal.ai.slack_app import posthog_code_slack_mention
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,patched,expect_classifier",
    [
        # File-only replies skip the classifier so the attachment isn't dropped.
        ("", True, False),
        # Replies with text still face the classifier even when files are attached.
        ("nice weather today", True, True),
        # Replays of histories recorded before the confirmation patch skip the prompt.
        ("", False, False),
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
        if activity_fn is posthog_code_slack_mention.enforce_posthog_code_billing_quota_activity:
            return False
        if activity_fn is posthog_code_slack_mention.classify_untagged_followup_activity:
            return True
        if activity_fn is posthog_code_slack_mention.request_untagged_followup_confirmation_activity:
            return False
        if activity_fn is posthog_code_slack_mention.classify_slack_app_model_override_activity:
            return None
        if activity_fn is posthog_code_slack_mention.forward_posthog_code_followup_activity:
            return True

        raise AssertionError(f"unexpected activity: {activity_fn.__name__}")

    with (
        patch.object(posthog_code_slack_mention.workflow, "patched", return_value=patched),
        # Runs outside a workflow context, where the real marker call would raise.
        patch.object(posthog_code_slack_mention.workflow, "deprecate_patch"),
        patch.object(posthog_code_slack_mention, "_execute_posthog_code_activity", side_effect=fake_execute_activity),
    ):
        await workflow.run(inputs)

    expected = ["enforce_posthog_code_billing_quota_activity"]
    if expect_classifier:
        expected.append("classify_untagged_followup_activity")
    if patched:
        expected.append("request_untagged_followup_confirmation_activity")
        # The model-override classifier sits above the follow-up/new-task split, so it
        # runs for a reply too — but only for histories that recorded it there.
        expected.append("classify_slack_app_model_override_activity")
    expected.append("forward_posthog_code_followup_activity")
    assert calls == expected


@pytest.mark.asyncio
async def test_confirmed_untagged_followup_skips_the_classifier_and_the_prompt() -> None:
    """The click that re-dispatches carries the answer, so asking again would
    loop: prompt, confirm, classify, prompt."""
    workflow = posthog_code_slack_mention.PostHogCodeSlackMentionWorkflow()
    calls: list[str] = []
    inputs = PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5679", "user": "U_BOB", "text": "and the export filter too"},
        integration_id=1,
        slack_team_id="T_SLACK",
        user_id=42,
        untagged_followup=True,
        untagged_followup_confirmed=True,
    )

    async def fake_execute_activity(activity_fn, *args):
        calls.append(activity_fn.__name__)
        if activity_fn is posthog_code_slack_mention.enforce_posthog_code_billing_quota_activity:
            return False
        if activity_fn is posthog_code_slack_mention.classify_slack_app_model_override_activity:
            return None
        if activity_fn is posthog_code_slack_mention.forward_posthog_code_followup_activity:
            return True
        raise AssertionError(f"unexpected activity: {activity_fn.__name__}")

    with (
        patch.object(posthog_code_slack_mention.workflow, "patched", return_value=True),
        patch.object(posthog_code_slack_mention, "_execute_posthog_code_activity", side_effect=fake_execute_activity),
    ):
        await workflow.run(inputs)

    assert calls == [
        "enforce_posthog_code_billing_quota_activity",
        "classify_slack_app_model_override_activity",
        "forward_posthog_code_followup_activity",
    ]
