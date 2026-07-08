# Workflows in this module run on the max-ai temporal task queue.
import json
from datetime import timedelta

from temporalio import exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app import derive_mention_workflow_id, mark_slack_app_message_processing_activity
from posthog.temporal.ai.slack_app.helpers.process_mention_message import (
    MentionSignalHandlersMixin,
    process_mention_message,
)
from posthog.temporal.ai.slack_app.types import (
    MarkSlackAppMessageProcessingInput,
    PostHogCodeSlackMentionWorkflowInputs,
    SlackAppMentionWorkflowInputs,
)
from posthog.temporal.common.base import PostHogWorkflow

SLACK_APP_MENTION_IDLE_TIMEOUT_SECONDS = 30
# Dedup keys carried across continue_as_new. Bounded so the carry-over payload
# stays small; old keys only matter for Slack retries, which arrive within
# minutes of the original event.
SLACK_APP_MENTION_MAX_PROCESSED_KEYS = 200


def derive_slack_app_mention_workflow_id(inputs: PostHogCodeSlackMentionWorkflowInputs) -> str | None:
    """Conversation-scoped workflow ID: one per thread (or DM thread).

    Anchored on the thread root ts — the same anchor the rest of the pipeline
    uses — so every message in a conversation resolves to the same workflow.
    Returns None when the event lacks a channel or ts; callers fall back to
    the per-message workflow.
    """
    event = inputs.event
    channel = event.get("channel")
    anchor = event.get("thread_ts") or event.get("ts")
    if not channel or not anchor:
        return None
    return f"slack-app-mention-{inputs.slack_team_id}:{channel}:{anchor}"


@workflow.defn(name="slack-app-mention")
class SlackAppMentionWorkflow(MentionSignalHandlersMixin, PostHogWorkflow):
    """Per-conversation queue over the mention pipeline.

    The per-message ``PostHogCodeSlackMentionWorkflow`` races when several
    messages land in one thread. This workflow serializes them: the webhook
    signal-with-starts one instance per conversation, messages queue up as
    ``new_message`` signals, and the loop feeds them one at a time through the
    shared ``process_mention_message`` orchestration. After the idle timeout
    with an empty queue the workflow completes; the next message simply starts
    a fresh instance, which finds the conversation's task via
    ``SlackThreadTaskMapping`` and continues in followup mode.
    """

    def __init__(self) -> None:
        super().__init__()
        self._queue: list[PostHogCodeSlackMentionWorkflowInputs] = []
        # Insertion-ordered so the continue_as_new carry-over stays deterministic
        # across replays (set iteration order is not).
        self._seen_keys: dict[str, None] = {}

    @workflow.signal
    async def new_message(self, message: PostHogCodeSlackMentionWorkflowInputs) -> None:
        # The per-message workflow ID doubles as the message's identity, so the
        # dedup rule stays single-sourced with derive_mention_workflow_id.
        key = derive_mention_workflow_id(message)
        if key in self._seen_keys:
            return
        self._seen_keys[key] = None
        self._queue.append(message)

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackAppMentionWorkflowInputs:
        loaded = json.loads(inputs[0])
        loaded["pending_messages"] = [
            PostHogCodeSlackMentionWorkflowInputs(**message) for message in loaded.get("pending_messages", [])
        ]
        return SlackAppMentionWorkflowInputs(**loaded)

    async def _mark_processing(self, message: PostHogCodeSlackMentionWorkflowInputs) -> None:
        """Swap the dispatch-time :hourglass: for :eyes: as the message leaves
        the queue. Mentions and DMs only — untagged thread followups get no
        dispatch reaction, and most are dropped by the chitchat classifier.
        """
        channel = message.event.get("channel")
        message_ts = message.event.get("ts")
        if message.untagged_followup or not channel or not message_ts:
            return
        try:
            await workflow.execute_activity(
                mark_slack_app_message_processing_activity,
                MarkSlackAppMessageProcessingInput(
                    integration_id=message.integration_id,
                    slack_team_id=message.slack_team_id,
                    channel=channel,
                    message_ts=message_ts,
                ),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except exceptions.ActivityError:
            # The activity swallows Slack errors itself; this only fires on a
            # timeout. Cosmetic either way — never stall the queue for it.
            workflow.logger.warning("slack_app_processing_reaction_activity_failed")

    @workflow.run
    async def run(self, inputs: SlackAppMentionWorkflowInputs) -> None:
        for key in inputs.processed_event_keys:
            self._seen_keys[key] = None
        for message in inputs.pending_messages:
            self._seen_keys.setdefault(derive_mention_workflow_id(message), None)
            self._queue.append(message)

        while True:
            try:
                await workflow.wait_condition(
                    lambda: bool(self._queue),
                    timeout=timedelta(seconds=SLACK_APP_MENTION_IDLE_TIMEOUT_SECONDS),
                )
            except TimeoutError:
                # Idle exit. Drain in-flight signal handlers and re-check: a
                # message landing between the timeout and the return must not
                # be dropped. A signal racing the completion command makes the
                # server fail the workflow task and replay, landing here again
                # with the queue non-empty. Once the workflow has fully closed,
                # the webhook's signal-with-start spawns a fresh instance.
                await workflow.wait_condition(workflow.all_handlers_finished)
                if self._queue:
                    continue
                return

            message = self._queue.pop(0)
            self._signals.reset()
            await self._mark_processing(message)
            # Never raises: internal errors are posted back to the thread, so
            # one poisoned message can't wedge the conversation's queue.
            await process_mention_message(message, self._signals)

            if workflow.info().is_continue_as_new_suggested():
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(
                    SlackAppMentionWorkflowInputs(
                        pending_messages=list(self._queue),
                        processed_event_keys=list(self._seen_keys)[-SLACK_APP_MENTION_MAX_PROCESSED_KEYS:],
                    )
                )
