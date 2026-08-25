# Workflows in this module run on the max-ai temporal task queue.
import json
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app import (
    POSTHOG_CODE_SLACK_MENTION_PICKER_GUIDANCE,
    PostHogCodeSlackMentionWorkflowInputs,
    SlackAppModelOverride,
    SlackAppModelOverrideInput,
    cascade_posthog_code_repository_activity,
    classify_posthog_code_task_needs_repo_activity,
    classify_slack_app_model_override_activity,
    classify_untagged_followup_activity,
    collect_posthog_code_thread_messages_activity,
    create_posthog_code_task_for_repo_activity,
    discover_posthog_code_repository_via_agent_activity,
    enforce_posthog_code_billing_quota_activity,
    forward_posthog_code_followup_activity,
    post_posthog_code_internal_error_activity,
    post_posthog_code_picker_timeout_activity,
    post_posthog_code_repo_picker_activity,
    request_untagged_followup_confirmation_activity,
)
from posthog.temporal.common.base import PostHogWorkflow

POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS = 10 * 60
POSTHOG_CODE_SLACK_PICKER_TIMEOUT_MINUTES = 15

# Temporal patch IDs — arbitrary strings recorded in workflow history. The
# pre-patch histories behind the first three have drained: this workflow's
# longest wait is the 15-minute repo picker, and it is bounded at an hour as a
# child of the queue workflow. Their gates are gone and only `deprecate_patch`
# remains, keeping the recorded marker compatible for executions in flight
# across the deploy that removes them. Standard two-step Temporal patch
# lifecycle: those calls come out once the histories that recorded a plain
# marker have drained in turn. The last two are younger and still gated, so they
# stay full `workflow.patched` branches until they drain too.
_PATCH_ID_FILE_ONLY_FOLLOWUP_BYPASS = "slack-file-only-followup-bypass-v1"
_PATCH_ID_FOLLOWUP_MODEL_CLASSIFIER = "slack-app-followup-model-classifier-v1"
_PATCH_ID_MODEL_CLASSIFIER = "slack-app-model-classifier-v1"
_PATCH_ID_NO_PERSONAL_GITHUB_GATE = "slack-no-personal-github-gate-v1"
_PATCH_ID_UNTAGGED_FOLLOWUP_CONFIRMATION = "slack-untagged-followup-confirmation-v1"


@workflow.defn(name="posthog-code-slack-mention-processing")
class PostHogCodeSlackMentionWorkflow(PostHogWorkflow):
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
        if not self._repo_selection_resolved:
            self._repo_selection_resolved = True
            self._selected_repo = None

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostHogCodeSlackMentionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return PostHogCodeSlackMentionWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostHogCodeSlackMentionWorkflowInputs) -> None:
        event = inputs.event
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        slack_user_id = event.get("user")

        if not channel or not thread_ts or not slack_user_id:
            return

        try:
            # Gate every workflow entry on the team's AI-credits quota before any
            # other activity runs. Webhook-level short-circuit catches the common
            # case (see products/slack_app/backend/api.py); this is the defense in
            # depth that also covers replays, manual workflow starts, and the race
            # where the webhook saw "not limited" but Redis flipped before we got
            # here.
            blocked = await _execute_posthog_code_activity(
                enforce_posthog_code_billing_quota_activity,
                inputs,
                channel,
                thread_ts,
                slack_user_id,
            )
            if blocked:
                return

            # Untagged thread replies face the Haiku classifier before any
            # forward. The webhook handler punted on this so its 3-second ack
            # budget stays unencumbered; here we run it under Temporal's retry
            # policy. Drop on chitchat or any failure (default-deny).
            # File-only replies skip the classifier: there is no text to
            # classify, and default-deny would silently drop the attachment.
            # Replies with text still face it even when files are attached, so
            # chitchat with a screenshot doesn't wake the agent.
            event_files = event.get("files")
            event_has_files = isinstance(event_files, list) and len(event_files) > 0
            file_only_followup = event_has_files and not (event.get("text") or "").strip()
            if inputs.untagged_followup and not inputs.untagged_followup_confirmed:
                if file_only_followup:
                    # The gate this replaces was only ever reached behind both
                    # flags, so only these histories carry the marker.
                    workflow.deprecate_patch(_PATCH_ID_FILE_ONLY_FOLLOWUP_BYPASS)
                else:
                    should_forward = await _execute_posthog_code_activity(
                        classify_untagged_followup_activity,
                        inputs,
                        channel,
                        thread_ts,
                        slack_user_id,
                        event.get("text", ""),
                    )
                    if not should_forward:
                        return

            # The reply is agent-directed. If the thread creator asked to be consulted
            # about other people's replies, this is the moment to ask: the prompt now
            # only interrupts someone over a message that would otherwise start work.
            # A confirmed run skips it — the answer is what re-dispatched this.
            if (
                inputs.untagged_followup
                and not inputs.untagged_followup_confirmed
                and workflow.patched(_PATCH_ID_UNTAGGED_FOLLOWUP_CONFIRMATION)
            ):
                awaiting_confirmation = await _execute_posthog_code_activity(
                    request_untagged_followup_confirmation_activity,
                    inputs,
                    channel,
                    thread_ts,
                    slack_user_id,
                )
                if awaiting_confirmation:
                    return

            # Read a model or effort request ("use fable for this one", "actually run
            # this on opus") out of the message. Classified above the follow-up/new-task
            # split because the mapping lookup that tells the two apart lives inside the
            # follow-up activity: one call here serves whichever path the message takes,
            # and recording the choice in history once stops a retry of either activity
            # from landing on a different model than the first attempt announced. The
            # feature flag is checked inside the activity — branching the workflow on a
            # flag would be non-deterministic on replay.
            model_override: SlackAppModelOverride | None = None
            classified_before_split = workflow.patched(_PATCH_ID_FOLLOWUP_MODEL_CLASSIFIER)
            if classified_before_split:
                model_override = await _execute_posthog_code_activity(
                    classify_slack_app_model_override_activity,
                    SlackAppModelOverrideInput(
                        integration_id=inputs.integration_id,
                        slack_team_id=inputs.slack_team_id,
                        event_text=event.get("text", ""),
                    ),
                )

                followup_handled = await _execute_posthog_code_activity(
                    forward_posthog_code_followup_activity,
                    inputs,
                    channel,
                    thread_ts,
                    slack_user_id,
                    event.get("text", ""),
                    event.get("ts"),
                    model_override,
                )
            else:
                # Pre-patch histories recorded this activity without the override, and
                # classified further down. Replaying them has to schedule the same call.
                followup_handled = await _execute_posthog_code_activity(
                    forward_posthog_code_followup_activity,
                    inputs,
                    channel,
                    thread_ts,
                    slack_user_id,
                    event.get("text", ""),
                    event.get("ts"),
                )
            if followup_handled:
                return

            # Untagged thread replies must not fall through to the new-task path.
            # The user never @mentioned us — they only typed in a thread that
            # used to have an active task. If the mapping is gone by the time we
            # got here, the right behaviour is to do nothing.
            if inputs.untagged_followup:
                return

            user_id = inputs.user_id

            # A forked run is the one case where the thread we read and the thread we
            # answer in are different. `channel`/`thread_ts` stay the DM throughout —
            # they own the task, the mapping, the reaction and every follow-up — while
            # the context block is built from the channel thread the user forked.
            # Unset for every other run, so both pairs coincide.
            context_channel = inputs.fork_source_channel or channel
            context_thread_ts = inputs.fork_source_thread_ts or thread_ts

            thread_messages = await _execute_posthog_code_activity(
                collect_posthog_code_thread_messages_activity,
                inputs,
                context_channel,
                context_thread_ts,
            )
            if not thread_messages:
                return

            repository: str | None
            # Set only on the ambiguous path that runs the discovery sandbox
            repo_research_task_id: str | None = None
            repo_research_run_id: str | None = None

            cascade = await _execute_posthog_code_activity(
                cascade_posthog_code_repository_activity,
                inputs,
                event.get("text", ""),
                user_id,
                thread_messages,
                event.get("ts"),
            )

            if cascade.mode == "auto":
                repository = cascade.repository
            elif cascade.mode == "no_repo":
                # Cascade emits `no_repo` whenever the mentioning user resolves no repos.
                # The mention still becomes a task. Whether the ask needs code is the
                # agent's call once it can see the request, and the agent is the one that
                # tells the user to connect GitHub if it turns out to need a repo. Deciding
                # that here meant a single false positive from the needs-repo classifier
                # walled a plain analytics question behind a Connect button.
                repository = None
                workflow.deprecate_patch(_PATCH_ID_NO_PERSONAL_GITHUB_GATE)
            else:
                # Multiple candidates and no explicit mention. Cheap Haiku
                # check first to skip the agent entirely for analytics/config
                # questions; otherwise hand off to the discovery agent.
                needs_repo = await _execute_posthog_code_activity(
                    classify_posthog_code_task_needs_repo_activity,
                    event.get("text", ""),
                    thread_messages,
                )
                if not needs_repo:
                    repository = None
                else:
                    outcome = await _execute_posthog_code_agent_activity(
                        discover_posthog_code_repository_via_agent_activity,
                        inputs,
                        channel,
                        event,
                        thread_messages,
                        user_id,
                    )
                    repo_research_task_id = outcome.repo_research_task_id
                    repo_research_run_id = outcome.repo_research_run_id

                    if outcome.status == "found":
                        repository = outcome.repository
                    elif outcome.status == "no_match":
                        repository = None
                    else:
                        # Agent crashed/timed out/hallucinated — italicize its reason
                        # above the picker guidance so the user sees why.
                        picker_guidance = f"_{outcome.reason}_\n\n{POSTHOG_CODE_SLACK_MENTION_PICKER_GUIDANCE}"
                        await _execute_posthog_code_activity(
                            post_posthog_code_repo_picker_activity,
                            inputs,
                            channel,
                            thread_ts,
                            slack_user_id,
                            event,
                            workflow.info().workflow_id,
                            picker_guidance,
                            True,
                            user_id,
                        )
                        try:
                            await workflow.wait_condition(
                                lambda: self._repo_selection_resolved,
                                timeout=timedelta(minutes=POSTHOG_CODE_SLACK_PICKER_TIMEOUT_MINUTES),
                            )
                        except TimeoutError:
                            await _execute_posthog_code_activity(
                                post_posthog_code_picker_timeout_activity, inputs, channel, thread_ts
                            )
                            return
                        repository = self._selected_repo
            workflow.deprecate_patch(_PATCH_ID_MODEL_CLASSIFIER)
            if not classified_before_split:
                # Where pre-patch histories classify: past every gate that can still
                # abandon the mention, so the call is only spent on a task that gets
                # created. Newer executions trade that for one classification shared
                # with the follow-up path, which retries far more often than it is
                # abandoned here.
                model_override = await _execute_posthog_code_activity(
                    classify_slack_app_model_override_activity,
                    SlackAppModelOverrideInput(
                        integration_id=inputs.integration_id,
                        slack_team_id=inputs.slack_team_id,
                        event_text=event.get("text", ""),
                    ),
                )

            await _execute_posthog_code_activity(
                create_posthog_code_task_for_repo_activity,
                inputs,
                channel,
                thread_ts,
                slack_user_id,
                user_id,
                event,
                thread_messages,
                repository,
                repo_research_task_id,
                repo_research_run_id,
                model_override,
            )
        except Exception as exc:
            workflow.logger.exception(
                "posthog_code_workflow_unhandled_exception",
                extra={
                    "channel": channel,
                    "thread_ts": thread_ts,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            await _execute_posthog_code_activity(
                post_posthog_code_internal_error_activity,
                inputs,
                channel,
                thread_ts,
            )


async def _execute_posthog_code_activity(activity_fn: Any, *args: Any) -> Any:
    return await workflow.execute_activity(
        activity_fn,
        args=args,
        start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )


async def _execute_posthog_code_agent_activity(activity_fn: Any, *args: Any) -> Any:
    """Wrapper for the discovery-agent activity.

    No retries: a hung agent shouldn't block the Slack thread for tens of
    minutes — the activity catches its own exceptions and returns
    `status='failed'` so the workflow falls through to the picker.
    """
    return await workflow.execute_activity(
        activity_fn,
        args=args,
        start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS),
        heartbeat_timeout=timedelta(minutes=5),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
