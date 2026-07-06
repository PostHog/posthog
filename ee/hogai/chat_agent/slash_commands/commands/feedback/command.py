from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from products.posthog_ai.backend.slash_commands.feedback import FeedbackCommand as FeedbackCommandCore

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.chat_agent.slash_commands.commands.base import build_slash_command_context
from ee.hogai.core.agent_modes.const import SlashCommandName
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class FeedbackCommand(SlashCommand):
    """LangGraph adapter for `/feedback` — extracts the feedback text from the thread and delegates
    the capture to the shared core."""

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
        context = build_slash_command_context(self._team, self._user, config)
        content = await FeedbackCommandCore(context).execute(feedback_content or "")
        return PartialAssistantState(messages=[AssistantMessage(content=content, id=str(uuid4()))])
