from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from products.posthog_ai.backend.slash_commands.base import TranscriptMessage
from products.posthog_ai.backend.slash_commands.ticket import TicketCommand as TicketCommandCore

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.chat_agent.slash_commands.commands.base import build_slash_command_context
from ee.hogai.core.agent_modes.compaction_manager import AnthropicConversationCompactionManager
from ee.hogai.utils.types import AssistantState, PartialAssistantState


def _is_ticket_command(content: str) -> bool:
    stripped = content.strip()
    return stripped == "/ticket" or stripped.startswith("/ticket ")


class LangGraphTranscriptSource:
    """Neutral transcript over the LangGraph `AssistantState`. Windows the messages with the
    compaction manager, then drops the triggering `/ticket` command so an empty transcript signals a
    first-message ticket — matching the sandbox runtime, whose log excludes the not-yet-persisted
    command turn."""

    _window_manager = AnthropicConversationCompactionManager()

    def __init__(self, state: AssistantState) -> None:
        self._state = state

    async def fetch(self) -> list[TranscriptMessage]:
        messages_in_window = self._window_manager.get_messages_in_window(
            self._state.messages, self._state.root_conversation_start_id
        )
        windowed = list(messages_in_window)
        if windowed and isinstance(windowed[-1], HumanMessage) and _is_ticket_command(windowed[-1].content):
            windowed = windowed[:-1]

        transcript: list[TranscriptMessage] = []
        for msg in windowed:
            if isinstance(msg, HumanMessage):
                transcript.append(TranscriptMessage(role="user", content=msg.content))
            elif isinstance(msg, AssistantMessage) and msg.content:
                transcript.append(TranscriptMessage(role="assistant", content=msg.content))
        return transcript


class TicketCommand(SlashCommand):
    """LangGraph adapter for `/ticket` — supplies a `LangGraphTranscriptSource` and delegates to the
    shared core."""

    def _is_first_message(self, state: AssistantState) -> bool:
        """Check if /ticket is the first message in the conversation."""
        human_messages = [msg for msg in state.messages if isinstance(msg, HumanMessage)]
        return len(human_messages) <= 1

    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        context = build_slash_command_context(self._team, self._user, config)
        content = await TicketCommandCore(context, LangGraphTranscriptSource(state)).execute("")
        return PartialAssistantState(messages=[AssistantMessage(content=content, id=str(uuid4()))])
