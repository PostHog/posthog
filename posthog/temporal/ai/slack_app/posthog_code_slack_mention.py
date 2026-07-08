# Workflows in this module run on the max-ai temporal task queue.
import json

from temporalio import workflow

from posthog.temporal.ai.slack_app.helpers.process_mention_message import (
    MentionSignalHandlersMixin,
    process_mention_message,
)
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs
from posthog.temporal.common.base import PostHogWorkflow


@workflow.defn(name="posthog-code-slack-mention-processing")
class PostHogCodeSlackMentionWorkflow(MentionSignalHandlersMixin, PostHogWorkflow):
    """One workflow per message — the pre-queue dispatch mode. When the
    ``slack-app-queue-workflow`` flag is on, dispatch goes to the
    per-conversation ``SlackAppMentionWorkflow`` instead; both drive messages
    through the shared ``process_mention_message`` orchestration.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostHogCodeSlackMentionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return PostHogCodeSlackMentionWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostHogCodeSlackMentionWorkflowInputs) -> None:
        await process_mention_message(inputs, self._signals)
