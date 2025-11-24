from abc import ABC, abstractmethod
from typing import Generic

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from posthog.models import Team, User

from ee.hogai.context import AssistantContextManager
from ee.hogai.utils.types.base import AssistantState, StateType


class PromptBuilder(ABC, Generic[StateType]):
    @abstractmethod
    async def get_prompts(self, state: StateType, config: RunnableConfig) -> list[BaseMessage]: ...


class AgentPromptBuilder(PromptBuilder[AssistantState]):
    def __init__(self, team: Team, user: User, context_manager: AssistantContextManager):
        self._team = team
        self._user = user
        self._context_manager = context_manager

    @abstractmethod
    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]: ...
