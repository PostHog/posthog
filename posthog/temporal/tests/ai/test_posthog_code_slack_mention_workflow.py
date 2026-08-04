import pytest
from unittest.mock import patch

from posthog.temporal.ai.slack_app import posthog_code_slack_mention
from posthog.temporal.ai.slack_app.types import (
    PostHogCodeFollowupIntent,
    PostHogCodeRepoCascadeOutcome,
    PostHogCodeSlackMentionWorkflowInputs,
)


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
        if activity_fn is posthog_code_slack_mention.enforce_posthog_code_billing_quota_activity:
            return False
        if activity_fn is posthog_code_slack_mention.classify_untagged_followup_activity:
            return True
        if activity_fn is posthog_code_slack_mention.forward_posthog_code_followup_activity:
            return True

        raise AssertionError(f"unexpected activity: {activity_fn.__name__}")

    with (
        patch.object(posthog_code_slack_mention.workflow, "patched", return_value=patched),
        patch.object(posthog_code_slack_mention, "_execute_posthog_code_activity", side_effect=fake_execute_activity),
    ):
        await workflow.run(inputs)

    expected = ["enforce_posthog_code_billing_quota_activity"]
    if expect_classifier:
        expected.append("classify_untagged_followup_activity")
    expected.append("forward_posthog_code_followup_activity")
    assert calls == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent,patched,expect_classifier,expect_create,expect_cascade",
    [
        # A scheduling ask is handled before the repository cascade, so it never
        # spins up the repo-discovery sandbox.
        ("schedule", True, True, True, False),
        # Anything non-schedule falls through to the normal run-now path.
        ("none", True, True, False, True),
        # Replays of histories recorded before the patch keep the old sequence:
        # no classifier, straight to the cascade.
        ("schedule", False, False, False, True),
    ],
)
async def test_followup_intent_short_circuits_before_the_repo_cascade(
    intent: str, patched: bool, expect_classifier: bool, expect_create: bool, expect_cascade: bool
) -> None:
    workflow = posthog_code_slack_mention.PostHogCodeSlackMentionWorkflow()
    calls: list[str] = []
    inputs = PostHogCodeSlackMentionWorkflowInputs(
        event={
            "channel": "C123",
            "ts": "1234.5679",
            "user": "U_ALICE",
            "text": "@PostHog check this in two weeks and report back here",
        },
        integration_id=1,
        slack_team_id="T_SLACK",
        user_id=42,
    )

    async def fake_execute_activity(activity_fn, *args):
        calls.append(activity_fn.__name__)
        if activity_fn is posthog_code_slack_mention.enforce_posthog_code_billing_quota_activity:
            return False
        if activity_fn is posthog_code_slack_mention.forward_posthog_code_followup_activity:
            return False
        if activity_fn is posthog_code_slack_mention.collect_posthog_code_thread_messages_activity:
            return [{"user": "Cory", "text": "we should watch this after launch", "ts": "1234.5678"}]
        if activity_fn is posthog_code_slack_mention.classify_posthog_code_followup_request_activity:
            return PostHogCodeFollowupIntent(
                intent=intent,  # type: ignore[arg-type]
                run_at="2026-08-14T09:00:00+00:00" if intent == "schedule" else None,
                what="Check cohort activation" if intent == "schedule" else None,
            )
        if activity_fn is posthog_code_slack_mention.create_posthog_code_followup_loop_activity:
            return True
        if activity_fn is posthog_code_slack_mention.cascade_posthog_code_repository_activity:
            # `needs_user_github` makes the workflow return right after the block activity,
            # so the fall-through path ends without choreographing the whole task-creation tail.
            return PostHogCodeRepoCascadeOutcome(mode="needs_user_github", repository=None, reason="test")
        if activity_fn is posthog_code_slack_mention.block_posthog_code_task_if_no_personal_github_activity:
            return None
        raise AssertionError(f"unexpected activity: {activity_fn.__name__}")

    with (
        patch.object(posthog_code_slack_mention.workflow, "patched", return_value=patched),
        patch.object(posthog_code_slack_mention, "_execute_posthog_code_activity", side_effect=fake_execute_activity),
    ):
        await workflow.run(inputs)

    assert ("classify_posthog_code_followup_request_activity" in calls) is expect_classifier
    assert ("create_posthog_code_followup_loop_activity" in calls) is expect_create
    assert ("cascade_posthog_code_repository_activity" in calls) is expect_cascade
