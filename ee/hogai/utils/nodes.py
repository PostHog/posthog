from abc import ABC, abstractmethod

from langchain_core.runnables import RunnableConfig

from posthog.models.team.team import Team

from .types import AssistantState, PartialAssistantState


class AssistantNode(ABC):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @abstractmethod
    def run(cls, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        raise NotImplementedError
