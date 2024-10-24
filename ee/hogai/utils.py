from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from operator import add
from typing import Annotated, Optional, TypedDict, Union

from langchain_core.agents import AgentAction
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START
from pydantic import BaseModel, Field

from posthog.models.team.team import Team
from posthog.schema import AssistantMessage, HumanMessage, RootAssistantMessage, VisualizationMessage

AssistantMessageUnion = Union[AssistantMessage, HumanMessage, VisualizationMessage]


class Conversation(BaseModel):
    messages: list[RootAssistantMessage] = Field(..., max_length=20)
    session_id: str


class AssistantState(TypedDict):
    messages: Annotated[Sequence[AssistantMessageUnion], add]
    intermediate_steps: Optional[list[tuple[AgentAction, Optional[str]]]]
    plan: Optional[str]
    tool_argument: Optional[str]


class AssistantNodeName(StrEnum):
    START = START
    END = END
    CREATE_TRENDS_PLAN = "create_trends_plan"
    CREATE_TRENDS_PLAN_TOOLS = "create_trends_plan_tools"
    GENERATE_TRENDS = "generate_trends_schema"
    GENERATE_TRENDS_TOOLS = "generate_trends_tools"


class AssistantNode(ABC):
    name: AssistantNodeName
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @abstractmethod
    def run(cls, state: AssistantState, config: RunnableConfig):
        raise NotImplementedError


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")
