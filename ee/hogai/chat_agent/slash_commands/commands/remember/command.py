from uuid import uuid4

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.core.agent_modes import SLASH_COMMAND_REMEMBER
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import CoreMemory


class RememberCommand(SlashCommand):
    """
    Handles the /remember slash command.
    Appends the provided content to the team's core memory.
    """

    def get_memory_content(self, state: AssistantState) -> str | None:
        """Extract the content to remember from the last human message."""
        for msg in reversed(state.messages):
            if isinstance(msg, HumanMessage):
                content = msg.content
                if content.startswith(SLASH_COMMAND_REMEMBER):
                    return content[len(SLASH_COMMAND_REMEMBER) :].strip()
                return None
        return None

    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        memory_content = self.get_memory_content(state)

        if not memory_content:
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="Please provide something to remember. Usage: `/remember <fact to remember>`",
                        id=str(uuid4()),
                    )
                ]
            )

        await sync_to_async(self._append_to_memory)(memory_content)

        return PartialAssistantState(
            messages=[AssistantMessage(content="I'll remember that for you.", id=str(uuid4()))]
        )

    def _append_to_memory(self, content: str) -> None:
        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        core_memory.append_core_memory(content)
