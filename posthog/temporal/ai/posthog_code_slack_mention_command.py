import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.utils import close_db_connections

POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS = 60
# Matches the mention workflow's picker wait window so the bot's behaviour is
# consistent across both flows. The lifetime of a command workflow that posts a
# picker is bounded by this timeout.
POSTHOG_CODE_SLACK_COMMAND_PICKER_TIMEOUT_MINUTES = 25


@dataclass
class PostHogCodeSlackMentionCommandWorkflowInputs:
    event: dict[str, Any]
    integration_ids: list[int]
    slack_team_id: str
    # Resolved at routing time. ``None`` only on in-flight workflow histories
    # started before this field existed; those fall back to the in-workflow
    # resolve activity below. Remove the fallback (and this field's optionality)
    # once the workflow history retention window has elapsed.
    user_id: int | None = None


@dataclass
class PostHogCodeSlackMentionCommandResult:
    """Outcome of the synchronous command-dispatch activity.

    ``status="done"`` means the command was handled (or refused) inline by the
    activity and the workflow has nothing left to do. ``status="needs_picker"``
    means the parsed command is a ``rules add`` without an inline repository,
    and the workflow must drive the interactive repo-picker flow against
    ``target_integration_id`` using ``pending_rule_text``.
    """

    status: str  # "done" | "needs_picker"
    pending_rule_text: str | None = None
    target_integration_id: int | None = None


@workflow.defn(name="posthog-code-slack-mention-command")
class PostHogCodeSlackMentionCommandWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._selected_repo: str | None = None
        self._repo_selection_resolved = False

    @workflow.signal
    async def repo_selected(self, repository: str) -> None:
        if not self._repo_selection_resolved:
            self._repo_selection_resolved = True
            self._selected_repo = repository

    @workflow.signal
    async def no_repo_needed(self) -> None:
        # Signal name mirrors the mention workflow's: the interactivity endpoint
        # routes by workflow_id, but addresses the signal by name. Both names
        # must match so a picker posted by either workflow can be resolved.
        if not self._repo_selection_resolved:
            self._repo_selection_resolved = True
            self._selected_repo = None

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostHogCodeSlackMentionCommandWorkflowInputs:
        loaded = json.loads(inputs[0])
        return PostHogCodeSlackMentionCommandWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostHogCodeSlackMentionCommandWorkflowInputs) -> None:
        from posthog.temporal.ai.posthog_code_slack_mention import (
            POSTHOG_CODE_SLACK_RULES_ADD_PICKER_GUIDANCE,
            PostHogCodeSlackMentionWorkflowInputs,
            block_posthog_code_task_if_no_personal_github_activity,
            create_posthog_code_routing_rule_activity,
            post_posthog_code_picker_timeout_activity,
            post_posthog_code_repo_picker_activity,
        )

        # New starts carry ``user_id`` from routing-time resolution and skip the
        # activity. Legacy histories started before the field existed deserialize
        # with ``user_id=None`` and replay through the activity so the recorded
        # command stream still matches. Drop this fallback (and make ``user_id``
        # required on inputs) once the workflow history retention window has
        # elapsed.
        user_id = inputs.user_id
        if user_id is None:
            user_id = await workflow.execute_activity(
                resolve_posthog_code_slack_command_user_activity,
                args=[inputs],
                start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if user_id is None:
                return

        result = await workflow.execute_activity(
            handle_posthog_code_slack_mention_command_activity,
            args=[inputs, user_id],
            start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if result.status != "needs_picker":
            return

        target_integration_id = result.target_integration_id
        pending_rule_text = result.pending_rule_text
        if target_integration_id is None or pending_rule_text is None:
            return

        event = inputs.event
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        slack_user_id = event.get("user")
        if not isinstance(channel, str) or not isinstance(thread_ts, str) or not isinstance(slack_user_id, str):
            return

        # The picker activities are written against the mention workflow's input
        # shape, but today they only read ``integration_id`` / ``slack_team_id``
        # / ``event`` from it. Synthesise a compatible record for the resolved
        # target so we can reuse the existing picker plumbing without
        # duplicating it. Forward ``user_id`` so any future activity that reads
        # it (e.g. for attribution) stays consistent with the surrounding
        # command workflow's resolved user.
        picker_inputs = PostHogCodeSlackMentionWorkflowInputs(
            event=inputs.event,
            integration_id=target_integration_id,
            slack_team_id=inputs.slack_team_id,
            user_id=inputs.user_id,
        )

        workflow.deprecate_patch("posthog-code-command-block-no-personal-github-2026-06")
        blocked = await workflow.execute_activity(
            block_posthog_code_task_if_no_personal_github_activity,
            args=[picker_inputs, channel, thread_ts, user_id],
            start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if blocked:
            return

        workflow.deprecate_patch("posthog-code-command-user-id-2026-06")
        await workflow.execute_activity(
            post_posthog_code_repo_picker_activity,
            args=[
                picker_inputs,
                channel,
                thread_ts,
                slack_user_id,
                inputs.event,
                workflow.info().workflow_id,
                POSTHOG_CODE_SLACK_RULES_ADD_PICKER_GUIDANCE,
                False,
                user_id,
            ],
            start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        try:
            await workflow.wait_condition(
                lambda: self._repo_selection_resolved,
                timeout=timedelta(minutes=POSTHOG_CODE_SLACK_COMMAND_PICKER_TIMEOUT_MINUTES),
            )
        except TimeoutError:
            await workflow.execute_activity(
                post_posthog_code_picker_timeout_activity,
                args=[picker_inputs, channel, thread_ts],
                start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return

        if not self._selected_repo:
            return

        await workflow.execute_activity(
            create_posthog_code_routing_rule_activity,
            args=[picker_inputs, channel, thread_ts, user_id, pending_rule_text, self._selected_repo],
            start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@activity.defn
@close_db_connections
def resolve_posthog_code_slack_command_user_activity(
    inputs: PostHogCodeSlackMentionCommandWorkflowInputs,
) -> int | None:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import resolve_posthog_user_from_event

    event = inputs.event
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    slack_user_id = event.get("user")
    if not channel or not thread_ts or not slack_user_id or not inputs.integration_ids:
        return None

    candidates = list(
        Integration.objects.filter(
            id__in=inputs.integration_ids,
            kind="slack",
            integration_id=inputs.slack_team_id,
        ).select_related("team", "team__organization")
    )
    if not candidates:
        return None

    probe = candidates[0]
    posthog_user = resolve_posthog_user_from_event(
        slack_user_id=slack_user_id,
        probe_integration=probe,
        candidate_integrations=candidates,
    )
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
@close_db_connections
def handle_posthog_code_slack_mention_command_activity(
    inputs: PostHogCodeSlackMentionCommandWorkflowInputs,
    user_id: int,
) -> PostHogCodeSlackMentionCommandResult:
    from posthog.models.integration import SlackIntegration

    from products.slack_app.backend.api import _parse_rules_command
    from products.slack_app.backend.services.commands import dispatch_rules_command, resolve_command_target

    event = inputs.event
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    slack_user_id = event.get("user")
    if not channel or not thread_ts or not slack_user_id:
        return PostHogCodeSlackMentionCommandResult(status="done")

    command = _parse_rules_command(event.get("text", ""))
    if command is None:
        return PostHogCodeSlackMentionCommandResult(status="done")

    candidates, result = resolve_command_target(
        slack_team_id=inputs.slack_team_id,
        command=command,
        slack_user_id=slack_user_id,
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
    )
    if not candidates:
        return PostHogCodeSlackMentionCommandResult(status="done")
    if result.integration is None:
        # Disambiguate "no access" (empty after access filtering) from
        # "multiple projects available" so users get an actionable hint.
        if not result.candidates:
            text = (
                "You don't have access to any PostHog project connected to this Slack workspace. "
                "Ask an admin to grant you access, then try again."
            )
        else:
            text = (
                "This Slack workspace is connected to multiple PostHog projects. "
                "Use `@PostHog project <id>` to set a default first, then re-run your command."
            )
        SlackIntegration(candidates[0]).client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=text,
        )
        return PostHogCodeSlackMentionCommandResult(status="done")

    target = result.integration

    # ``rules add`` without an inline repo needs the interactive picker, which
    # only a workflow can drive (it owns the signal). Hand control back so the
    # workflow can post the picker against the resolved target and wait for
    # the user's selection.
    if command.action == "add" and not command.repository:
        return PostHogCodeSlackMentionCommandResult(
            status="needs_picker",
            pending_rule_text=command.rule_text,
            target_integration_id=target.id,
        )

    dispatch_rules_command(
        command,
        SlackIntegration(target),
        target,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        slack_workspace_id=inputs.slack_team_id,
        user_id=user_id,
        workspace_candidates=candidates,
    )
    return PostHogCodeSlackMentionCommandResult(status="done")
