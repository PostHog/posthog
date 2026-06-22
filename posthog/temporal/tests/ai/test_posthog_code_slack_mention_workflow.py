import pytest
from unittest.mock import patch

from posthog.temporal.ai.slack_app import posthog_code_slack_mention
from posthog.temporal.ai.slack_app.types import (
    PostHogCodeRepoCascadeOutcome,
    PostHogCodeSlackMentionWorkflowInputs,
    PostHogCodeTaskRoutingOutcome,
)


def _make_inputs(text: str = "summarize this Slack thread") -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": text},
        integration_id=1,
        slack_team_id="T_SLACK",
        user_id=42,
    )


@pytest.mark.asyncio
async def test_general_task_routing_skips_repository_connector() -> None:
    workflow = posthog_code_slack_mention.PostHogCodeSlackMentionWorkflow()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def fake_execute_activity(activity_fn, *args):
        calls.append((activity_fn.__name__, args))
        if activity_fn is posthog_code_slack_mention.enforce_posthog_code_billing_quota_activity:
            return False
        if activity_fn is posthog_code_slack_mention.forward_posthog_code_followup_activity:
            return False
        if activity_fn is posthog_code_slack_mention.collect_posthog_code_thread_messages_activity:
            return [{"user": "Alice", "text": "summarize this Slack thread", "ts": "1234.5678"}]
        if activity_fn is posthog_code_slack_mention.classify_posthog_code_task_routing_activity:
            return PostHogCodeTaskRoutingOutcome(
                task_kind="general",
                required_connectors=["slack_thread", "posthog_mcp"],
                reason="built_in_general_connectors",
            )
        if activity_fn is posthog_code_slack_mention.create_posthog_code_task_for_repo_activity:
            return None

        raise AssertionError(f"unexpected activity: {activity_fn.__name__}")

    with (
        patch.object(posthog_code_slack_mention.workflow, "patched", return_value=True),
        patch.object(posthog_code_slack_mention, "_execute_posthog_code_activity", side_effect=fake_execute_activity),
    ):
        await workflow.run(_make_inputs())

    activity_names = [name for name, _args in calls]
    assert "cascade_posthog_code_repository_activity" not in activity_names
    assert "block_posthog_code_task_if_no_personal_github_activity" not in activity_names

    create_call = next(args for name, args in calls if name == "create_posthog_code_task_for_repo_activity")
    assert create_call[7] is None
    assert create_call[10] == "general"


@pytest.mark.asyncio
async def test_coding_task_routing_runs_repository_connector_cascade() -> None:
    workflow = posthog_code_slack_mention.PostHogCodeSlackMentionWorkflow()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def fake_execute_activity(activity_fn, *args):
        calls.append((activity_fn.__name__, args))
        if activity_fn is posthog_code_slack_mention.enforce_posthog_code_billing_quota_activity:
            return False
        if activity_fn is posthog_code_slack_mention.forward_posthog_code_followup_activity:
            return False
        if activity_fn is posthog_code_slack_mention.collect_posthog_code_thread_messages_activity:
            return [{"user": "Alice", "text": "open a PR", "ts": "1234.5678"}]
        if activity_fn is posthog_code_slack_mention.classify_posthog_code_task_routing_activity:
            return PostHogCodeTaskRoutingOutcome(
                task_kind="coding",
                required_connectors=["slack_thread", "posthog_mcp", "github_repository"],
                reason="github_repository_required",
            )
        if activity_fn is posthog_code_slack_mention.cascade_posthog_code_repository_activity:
            return PostHogCodeRepoCascadeOutcome(mode="auto", repository="posthog/posthog", reason="single_repo")
        if activity_fn is posthog_code_slack_mention.block_posthog_code_task_if_no_personal_github_activity:
            return False
        if activity_fn is posthog_code_slack_mention.create_posthog_code_task_for_repo_activity:
            return None

        raise AssertionError(f"unexpected activity: {activity_fn.__name__}")

    with (
        patch.object(posthog_code_slack_mention.workflow, "patched", return_value=True),
        patch.object(posthog_code_slack_mention, "_execute_posthog_code_activity", side_effect=fake_execute_activity),
    ):
        await workflow.run(_make_inputs("open a PR"))

    activity_names = [name for name, _args in calls]
    assert "cascade_posthog_code_repository_activity" in activity_names
    assert "block_posthog_code_task_if_no_personal_github_activity" in activity_names

    create_call = next(args for name, args in calls if name == "create_posthog_code_task_for_repo_activity")
    assert create_call[7] == "posthog/posthog"
    assert create_call[10] == "coding"
