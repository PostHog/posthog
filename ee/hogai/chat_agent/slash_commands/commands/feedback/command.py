from uuid import uuid4

import posthoganalytics
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.core.agent_modes import SlashCommandName
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class FeedbackCommand(SlashCommand):
    """
    Handles the /feedback slash command.
    Captures user feedback about their PostHog AI experience.
    """

    def get_feedback_content(self, state: AssistantState) -> str | None:
        """Extract the feedback text from the last human message."""
        for msg in reversed(state.messages):
            if isinstance(msg, HumanMessage):
                content = msg.content
                if content.startswith(SlashCommandName.FIELD_FEEDBACK):
                    return content[len(SlashCommandName.FIELD_FEEDBACK) :].strip()
                return None
        return None

    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        feedback_content = self.get_feedback_content(state)

        if not feedback_content:
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="Please provide your feedback for PostHog AI. Usage: `/feedback <your feedback>`",
                        id=str(uuid4()),
                    )
                ]
            )

        conversation_id = config.get("configurable", {}).get("thread_id")
        trace_id = config.get("configurable", {}).get("trace_id")

        # Capture feedback event
        posthoganalytics.capture(
            distinct_id=str(self._user.distinct_id),
            event="$ai_feedback",
            properties={
                "$ai_feedback_text": feedback_content,
                "$ai_session_id": conversation_id,
                "$ai_trace_id": trace_id,
            },
        )

        return PartialAssistantState(
            messages=[AssistantMessage(content="Thanks for making PostHog AI better!", id=str(uuid4()))]
        )
