from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from langchain_core.runnables import RunnableConfig

from products.posthog_ai.backend.slash_commands.base import SlashCommandContext

from ee.hogai.utils.types import AssistantState, PartialAssistantState

if TYPE_CHECKING:
    from posthog.models import Team, User


def _coerce_conversation_id(thread_id: object) -> UUID:
    """LangGraph thread ids are conversation UUID strings in production; fall back to a deterministic
    UUID for the few commands that don't read it (so non-UUID test thread ids still resolve)."""
    try:
        return UUID(str(thread_id))
    except (ValueError, TypeError):
        return uuid5(NAMESPACE_URL, str(thread_id))


def build_slash_command_context(team: "Team", user: "User", config: RunnableConfig) -> SlashCommandContext:
    """Resolve the runtime-agnostic command context from the LangGraph RunnableConfig. Attribution
    is available on LangGraph (generations carry `$ai_session_id`), so the flag stays True."""
    configurable = config.get("configurable", {})
    return SlashCommandContext(
        team=team,
        user=user,
        conversation_id=_coerce_conversation_id(configurable.get("thread_id")),
        trace_id=configurable.get("trace_id"),
        billing_context=configurable.get("billing_context"),
        conversation_attribution_available=True,
    )


class SlashCommand(ABC):
    """
    Base class for slash commands.

    Slash commands are executed directly by the SlashCommandHandlerNode,
    not as separate graph nodes. This simplifies the graph structure
    and makes it easier to add new commands.
    """

    def __init__(self, team: "Team", user: "User"):
        self._team = team
        self._user = user

    @abstractmethod
    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        """
        Execute the slash command and return the result state.

        Args:
            config: The runnable config containing thread_id and other metadata
            state: The current assistant state

        Returns:
            PartialAssistantState with messages to send to the user
        """
        raise NotImplementedError
