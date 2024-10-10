from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Generic, TypeVar

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from posthog.models.team.team import Team

llm_gpt_4o = ChatOpenAI(model="gpt-4o", temperature=0.7, streaming=True)


class AssistantState(BaseModel):
    messages: Annotated[Sequence[BaseMessage], add_messages]


class AssistantNodeName(StrEnum):
    START = START
    END = END
    CREATE_TRENDS_PLAN = "create_trends_plan"
    CREATE_TRENDS_PLAN_TOOLS = "create_trends_plan_tools"
    GENERATE_TRENDS = "generate_trends_schema"
    GENERATE_TRENDS_TOOLS = "generate_trends_tools"


T = TypeVar("T", bound=AssistantState)
R = TypeVar("R", bound=AssistantState)


class AssistantNode(ABC, Generic[T, R]):
    name: AssistantNodeName
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @abstractmethod
    def run(cls, state: T) -> R:
        raise NotImplementedError


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")
