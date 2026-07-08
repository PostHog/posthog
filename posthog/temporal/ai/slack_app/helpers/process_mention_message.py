"""Shared per-message mention orchestration.

This is workflow-side code: it runs inside a Temporal workflow and must stay
deterministic — no I/O, no Django, everything external goes through
activities. Both the per-message ``PostHogCodeSlackMentionWorkflow`` and the
per-conversation ``SlackAppMentionWorkflow`` drive their messages through
``process_mention_message``. Activity-side utilities live in this package's
``__init__``.
"""

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app import (
    POSTHOG_CODE_SLACK_MENTION_PICKER_GUIDANCE,
    PostHogCodeSlackMentionWorkflowInputs,
    block_posthog_code_task_if_no_personal_github_activity,
    cascade_posthog_code_repository_activity,
    classify_posthog_code_task_needs_repo_activity,
    classify_untagged_followup_activity,
    collect_posthog_code_thread_messages_activity,
    create_posthog_code_task_for_repo_activity,
    discover_posthog_code_repository_via_agent_activity,
    enforce_posthog_code_billing_quota_activity,
    forward_posthog_code_followup_activity,
    post_posthog_code_authorship_timeout_activity,
    post_posthog_code_internal_error_activity,
    post_posthog_code_picker_timeout_activity,
    post_posthog_code_repo_picker_activity,
    resolve_posthog_code_authorship_activity,
    resolve_posthog_code_slack_user_activity,
)

POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS = 10 * 60
POSTHOG_CODE_SLACK_PICKER_TIMEOUT_MINUTES = 15


class MentionSignalState:
    """Interactive-signal state for one mention's processing.

    Owned by whichever workflow class hosts the processing (the per-message
    mention workflow or the per-conversation queue workflow); its signal
    handlers write here and ``process_mention_message`` waits on it. The queue
    workflow resets it between messages, so a click on a stale picker from an
    earlier message can, in rare cases, resolve the currently pending one —
    accepted limitation.
    """

    def __init__(self) -> None:
        self.selected_repo: str | None
        self.repo_selection_resolved: bool
        self.authorship_resolved: bool
        self.reset()

    def reset(self) -> None:
        self.selected_repo = None
        self.repo_selection_resolved = False
        self.authorship_resolved = False

    def resolve_repo_selection(self, repository: str | None) -> None:
        """First click wins; later picker clicks for the same wait are ignored."""
        if not self.repo_selection_resolved:
            self.repo_selection_resolved = True
            self.selected_repo = repository

    def confirm_authorship(self) -> None:
        self.authorship_resolved = True


class MentionSignalHandlersMixin:
    """The interactive Slack signals, shared by both workflow classes.

    The webhook signals by name against an untyped workflow handle, so the
    handler names are a cross-class contract — inheriting them from one place
    keeps the two dispatch modes from drifting apart.
    """

    def __init__(self) -> None:
        super().__init__()
        self._signals = MentionSignalState()

    @workflow.signal
    async def repo_selected(self, repository: str) -> None:
        self._signals.resolve_repo_selection(repository)

    @workflow.signal
    async def no_repo_needed(self) -> None:
        self._signals.resolve_repo_selection(None)

    @workflow.signal
    async def authorship_confirmed(self) -> None:
        self._signals.confirm_authorship()


async def _resolve_authorship(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    signals: MentionSignalState,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
    repository: str,
) -> bool:
    """Return True if the workflow must stop (blocked or timed out); False to proceed."""
    status = await _execute_posthog_code_activity(
        resolve_posthog_code_authorship_activity,
        inputs,
        channel,
        thread_ts,
        slack_user_id,
        user_id,
        workflow.info().workflow_id,
        repository,
    )
    if status == "proceed":
        return False
    if status == "awaiting_confirmation":
        try:
            await workflow.wait_condition(
                lambda: signals.authorship_resolved,
                timeout=timedelta(minutes=POSTHOG_CODE_SLACK_PICKER_TIMEOUT_MINUTES),
            )
        except TimeoutError:
            await _execute_posthog_code_activity(
                post_posthog_code_authorship_timeout_activity, inputs, channel, thread_ts
            )
            return True
        return False
    return True


async def process_mention_message(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    signals: MentionSignalState,
) -> None:
    """Full per-message orchestration: quota gate -> followup classify/forward ->
    thread collect -> repo cascade/picker -> authorship gate -> create task.

    Catches its own exceptions (posts an internal-error reply); never raises,
    so a queue workflow calling it in a loop survives a poisoned message.
    """
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
        if inputs.untagged_followup:
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

        # New starts carry ``user_id`` from routing-time resolution and skip
        # the activity. Legacy histories started before the field existed
        # deserialize with ``user_id=None`` and replay through the activity so
        # the recorded command stream still matches. Drop this fallback (and
        # make ``user_id`` required on inputs) once the workflow history
        # retention window has elapsed.
        if inputs.user_id is not None:
            user_id = inputs.user_id
        else:
            user_id = await _execute_posthog_code_activity(
                resolve_posthog_code_slack_user_activity, inputs, channel, thread_ts, slack_user_id
            )
            if not user_id:
                return

        thread_messages = await _execute_posthog_code_activity(
            collect_posthog_code_thread_messages_activity,
            inputs,
            channel,
            thread_ts,
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
        )

        if cascade.mode == "auto":
            repository = cascade.repository
        elif cascade.mode == "no_repo":
            # Cascade only emits `no_repo` when neither the team nor the
            # mentioning user has any GitHub install. Classify first so
            # non-coding asks ("how do I configure retention?") still
            # answer with no repo; coding asks surface the connect-personal-
            # GitHub prompt instead of silently no-op'ing.
            repository = None
            needs_repo = await _execute_posthog_code_activity(
                classify_posthog_code_task_needs_repo_activity,
                event.get("text", ""),
                thread_messages,
            )
            if needs_repo:
                blocked = await _execute_posthog_code_activity(
                    block_posthog_code_task_if_no_personal_github_activity,
                    inputs,
                    channel,
                    thread_ts,
                    user_id,
                )
                if blocked:
                    return
        elif cascade.mode == "needs_user_github":
            # Team has GitHub, but the mentioning user hasn't connected their
            # personal install. Fire the gate so they get the Connect button
            # instead of a silently no-repo task.
            await _execute_posthog_code_activity(
                block_posthog_code_task_if_no_personal_github_activity,
                inputs,
                channel,
                thread_ts,
                user_id,
            )
            return
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
                            lambda: signals.repo_selection_resolved,
                            timeout=timedelta(minutes=POSTHOG_CODE_SLACK_PICKER_TIMEOUT_MINUTES),
                        )
                    except TimeoutError:
                        await _execute_posthog_code_activity(
                            post_posthog_code_picker_timeout_activity, inputs, channel, thread_ts
                        )
                        return
                    repository = signals.selected_repo
        if repository:
            if workflow.patched("posthog-code-authorship-confirm-2026-06"):
                if await _resolve_authorship(inputs, signals, channel, thread_ts, slack_user_id, user_id, repository):
                    return
            elif await _gate_on_personal_github(inputs, channel, thread_ts, user_id):
                return
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


async def _gate_on_personal_github(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    user_id: int,
) -> bool:
    """Return True when the workflow must abort because the mentioner has no personal GitHub."""
    return await _execute_posthog_code_activity(
        block_posthog_code_task_if_no_personal_github_activity,
        inputs,
        channel,
        thread_ts,
        user_id,
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
