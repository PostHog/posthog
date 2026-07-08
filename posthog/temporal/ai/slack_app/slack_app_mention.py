# Workflows in this module run on the max-ai temporal task queue.
import json
from datetime import timedelta
from typing import Any

from temporalio import exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app import (
    derive_mention_workflow_id,
    mark_slack_app_message_processing_activity,
    mark_slack_app_message_queued_activity,
)
from posthog.temporal.ai.slack_app.helpers.process_mention_message import (
    MentionSignalHandlersMixin,
    process_mention_message,
)
from posthog.temporal.ai.slack_app.types import (
    PostHogCodeSlackMentionWorkflowInputs,
    SlackAppMentionWorkflowInputs,
    SlackAppMessageReactionInput,
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

    The FIFO and dedup guarantees are scoped to one instance: the queue and
    the seen-key set die when the workflow completes, and a fresh instance
    starts empty. Ordering still holds across the boundary — a fresh instance
    only ever starts after the previous one finished with an empty queue —
    but a Slack event retry arriving after the idle window is no longer
    deduped and gets processed again.
    """

    def __init__(self) -> None:
        super().__init__()
        self._queue: list[PostHogCodeSlackMentionWorkflowInputs] = []
        self._processing = False
        # Dedup for Slack event redeliveries: signals have no server-side
        # dedup the way per-message workflow IDs did. A dict, not a set, so
        # iteration order stays deterministic for the continue_as_new carry-over.
        self._seen_keys: dict[str, None] = {}

    @workflow.signal
    async def new_message(self, message: PostHogCodeSlackMentionWorkflowInputs) -> None:
        # The per-message workflow ID doubles as the message's identity, so the
        # dedup rule stays single-sourced with derive_mention_workflow_id.
        key = derive_mention_workflow_id(message)
        if key in self._seen_keys:
            return
        self._seen_keys[key] = None
        # Only a message that waits behind another gets the queued reaction.
        will_wait = self._processing or bool(self._queue)
        self._queue.append(message)
        if will_wait:
            await self._react(message, mark_slack_app_message_queued_activity)

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackAppMentionWorkflowInputs:
        loaded = json.loads(inputs[0])
        loaded["pending_messages"] = [
            PostHogCodeSlackMentionWorkflowInputs(**message) for message in loaded.get("pending_messages", [])
        ]
        return SlackAppMentionWorkflowInputs(**loaded)

    async def _react(self, message: PostHogCodeSlackMentionWorkflowInputs, reaction_activity: Any) -> None:
        """Run one of the reaction activities for a mention or DM. Untagged
        thread followups get no reactions — they were never addressed to the
        bot, and most are dropped by the chitchat classifier.
        """
        channel = message.event.get("channel")
        message_ts = message.event.get("ts")
        if message.untagged_followup or not channel or not message_ts:
            return
        try:
            await workflow.execute_activity(
                reaction_activity,
                SlackAppMessageReactionInput(
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
            workflow.logger.warning("slack_app_reaction_activity_failed")

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
            self._processing = True
            await self._react(message, mark_slack_app_message_processing_activity)
            # Never raises: internal errors are posted back to the thread, so
            # one poisoned message can't wedge the conversation's queue.
            await process_mention_message(message, self._signals)
            self._processing = False

            # A long-lived conversation would eventually hit Temporal's history
            # cap, so restart the run with fresh history, carrying over the
            # waiting messages and recent dedup keys. Handlers are drained
            # first so a message mid-signal isn't lost from the queue snapshot.
            if workflow.info().is_continue_as_new_suggested():
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(
                    SlackAppMentionWorkflowInputs(
                        pending_messages=list(self._queue),
                        processed_event_keys=list(self._seen_keys)[-SLACK_APP_MENTION_MAX_PROCESSED_KEYS:],
                    )
                )
