import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS = 60


@dataclass
class PostHogCodeSlackMentionCommandWorkflowInputs:
    event: dict[str, Any]
    integration_ids: list[int]
    slack_team_id: str


@workflow.defn(name="posthog-code-slack-mention-command")
class PostHogCodeSlackMentionCommandWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostHogCodeSlackMentionCommandWorkflowInputs:
        loaded = json.loads(inputs[0])
        return PostHogCodeSlackMentionCommandWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostHogCodeSlackMentionCommandWorkflowInputs) -> None:
        user_id = await workflow.execute_activity(
            resolve_posthog_code_slack_command_user_activity,
            args=[inputs],
            start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if user_id is None:
            return
        await workflow.execute_activity(
            handle_posthog_code_slack_mention_command_activity,
            args=[inputs, user_id],
            start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@activity.defn
def resolve_posthog_code_slack_command_user_activity(
    inputs: PostHogCodeSlackMentionCommandWorkflowInputs,
) -> int | None:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import _resolve_posthog_user_from_event

    event = inputs.event
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    slack_user_id = event.get("user")
    if not channel or not thread_ts or not slack_user_id or not inputs.integration_ids:
        return None

    probe = (
        Integration.objects.filter(
            id__in=inputs.integration_ids,
            kind="slack-posthog-code",
            integration_id=inputs.slack_team_id,
        )
        .select_related("team", "team__organization")
        .first()
    )
    if probe is None:
        return None

    posthog_user = _resolve_posthog_user_from_event(slack_user_id=slack_user_id, probe_integration=probe)
    if posthog_user is None:
        SlackIntegration(probe).client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=(
                "I couldn't find your PostHog account in any organization connected to this Slack "
                "workspace. Ask an admin to invite you, then mention me again."
            ),
        )
        return None
    return posthog_user.id


@activity.defn
def handle_posthog_code_slack_mention_command_activity(
    inputs: PostHogCodeSlackMentionCommandWorkflowInputs,
    user_id: int,
) -> None:
    from posthog.models.integration import SlackIntegration

    from products.slack_app.backend.api import _parse_rules_command
    from products.slack_app.backend.services.commands import dispatch_rules_command, resolve_command_target

    event = inputs.event
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    slack_user_id = event.get("user")
    if not channel or not thread_ts or not slack_user_id:
        return

    command = _parse_rules_command(event.get("text", ""))
    if command is None:
        return

    candidates, integration = resolve_command_target(
        slack_team_id=inputs.slack_team_id,
        command=command,
        slack_user_id=slack_user_id,
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
    )
    if not candidates:
        return
    if integration is None:
        SlackIntegration(candidates[0]).client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=(
                "This Slack workspace is connected to multiple PostHog projects. "
                "Use `@PostHog project <id>` to set a default first, then re-run your command."
            ),
        )
        return

    dispatch_rules_command(
        command,
        SlackIntegration(integration),
        integration,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        slack_workspace_id=inputs.slack_team_id,
        user_id=user_id,
        workspace_candidates=candidates,
    )
