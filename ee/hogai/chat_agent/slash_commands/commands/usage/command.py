from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage

from products.posthog_ai.backend.slash_commands.usage import UsageCommand as UsageCommandCore

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.chat_agent.slash_commands.commands.base import build_slash_command_context
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class UsageCommand(SlashCommand):
    """LangGraph adapter for `/usage` — delegates to the shared core and wraps the reply as state."""

    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        context = build_slash_command_context(self._team, self._user, config)
        content = await UsageCommandCore(context).execute("")
        return PartialAssistantState(messages=[AssistantMessage(content=content, id=str(uuid4()))])
