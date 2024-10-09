from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START
from langgraph.graph.message import add_messages

from posthog.models.team.team import Team

llm_gpt_4o = ChatOpenAI(model="gpt-4o", temperature=0.7)


class AssistantState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    team: Team


class AssistantNodeName(StrEnum):
    START = START
    END = END
    CREATE_TRENDS_PLAN = "create_trends_plan"
    CREATE_TRENDS_PLAN_TOOLS = "create_trends_plan_tools"
    GENERATE_TRENDS = "generate_trends_schema"


class AssistantNode(ABC):
    name: AssistantNodeName

    @classmethod
    @abstractmethod
    def run(cls, state: AssistantState) -> AssistantState:
        raise NotImplementedError


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")


def generate_xml_tag(tag_name: str, content: str) -> str:
    return f"\n<{tag_name}>\n{content.strip()}\n</{tag_name}>\n"
