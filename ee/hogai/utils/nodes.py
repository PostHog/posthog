from abc import ABC, abstractmethod

from langchain_core.runnables import RunnableConfig

from ee.models.assistant import CoreMemory
from posthog.models.team.team import Team

from .types import AssistantState, PartialAssistantState


class AssistantNode(ABC):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @abstractmethod
    def run(cls, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        raise NotImplementedError

    @property
    def core_memory(self) -> CoreMemory | None:
        try:
            return CoreMemory.objects.get(team=self._team)
        except CoreMemory.DoesNotExist:
            return None

    @property
    def product_core_memory(self) -> str:
        if not self.core_memory:
            return ""
        return self.core_memory.formatted_text
