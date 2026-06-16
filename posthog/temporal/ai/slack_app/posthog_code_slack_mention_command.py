import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app import (
    POSTHOG_CODE_SLACK_RULES_ADD_PICKER_GUIDANCE,
    PostHogCodeSlackMentionCommandWorkflowInputs,
    PostHogCodeSlackMentionWorkflowInputs,
    block_posthog_code_task_if_no_personal_github_activity,
    create_posthog_code_routing_rule_activity,
    handle_posthog_code_slack_mention_command_activity,
    post_posthog_code_picker_timeout_activity,
    post_posthog_code_repo_picker_activity,
    resolve_posthog_code_slack_command_user_activity,
)
from posthog.temporal.common.base import PostHogWorkflow

POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS = 60
# Matches the mention workflow's picker wait window so the bot's behaviour is
# consistent across both flows. The lifetime of a command workflow that posts a
# picker is bounded by this timeout.
POSTHOG_CODE_SLACK_COMMAND_PICKER_TIMEOUT_MINUTES = 25


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

        blocked = await workflow.execute_activity(
            block_posthog_code_task_if_no_personal_github_activity,
            args=[picker_inputs, channel, thread_ts, user_id],
            start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_COMMAND_ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if blocked:
            return

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
