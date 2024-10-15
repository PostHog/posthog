from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.agents import AgentAction
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from posthog.models.team.team import Team

llm_gpt_4o = ChatOpenAI(model="gpt-4o", temperature=0.7, streaming=True)


class AssistantMessageType(StrEnum):
    VISUALIZATION = "visualization"


class VisualizationMessagePayload(BaseModel):
    type: Literal[AssistantMessageType.VISUALIZATION]
    plan: str


class AssistantMessage(BaseMessage):
    payload: Optional[VisualizationMessagePayload] = Field(None, discriminator="type")


class AssistantState(TypedDict):
    messages: Annotated[Sequence[AssistantMessage], add_messages]
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
    def run(cls, state: AssistantState) -> AssistantState:
        raise NotImplementedError


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")
