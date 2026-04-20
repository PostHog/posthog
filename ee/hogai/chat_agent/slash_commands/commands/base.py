from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.types import AssistantState, PartialAssistantState

if TYPE_CHECKING:
    from posthog.models import Team, User


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
