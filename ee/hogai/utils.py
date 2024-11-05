import operator
from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Optional, TypedDict, Union

from langchain_core.agents import AgentAction
from langchain_core.messages import HumanMessage as LangchainHumanMessage, merge_message_runs
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START
from pydantic import BaseModel, Field

from posthog.models.team.team import Team
from posthog.schema import (
    AssistantMessage,
    FailureMessage,
    HumanMessage,
    RootAssistantMessage,
    RouterMessage,
    VisualizationMessage,
)

AssistantMessageUnion = Union[AssistantMessage, HumanMessage, VisualizationMessage, FailureMessage, RouterMessage]


class Conversation(BaseModel):
    messages: list[RootAssistantMessage] = Field(..., min_length=1, max_length=20)
    session_id: str


class AssistantState(TypedDict, total=False):
    messages: Annotated[Sequence[AssistantMessageUnion], operator.add]
    intermediate_steps: Optional[list[tuple[AgentAction, Optional[str]]]]
    plan: Optional[str]


class AssistantNodeName(StrEnum):
    START = START
    END = END
    ROUTER = "router"
    CREATE_TRENDS_PLAN = "create_trends_plan"
    CREATE_TRENDS_PLAN_TOOLS = "create_trends_plan_tools"
    GENERATE_TRENDS = "generate_trends_schema"
    GENERATE_TRENDS_TOOLS = "generate_trends_tools"
    CREATE_FUNNEL_PLAN = "create_funnel_plan"


class AssistantNode(ABC):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @abstractmethod
    def run(cls, state: AssistantState, config: RunnableConfig) -> AssistantState:
        raise NotImplementedError


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")


def merge_human_messages(messages: list[LangchainHumanMessage]) -> list[LangchainHumanMessage]:
    """
    Filters out duplicated human messages and merges them into one message.
    """
    contents = set()
    filtered_messages = []
    for message in messages:
        if message.content in contents:
            continue
        contents.add(message.content)
        filtered_messages.append(message)
    return merge_message_runs(filtered_messages)


def filter_visualization_conversation(
    messages: Sequence[AssistantMessageUnion],
) -> tuple[list[LangchainHumanMessage], list[VisualizationMessage]]:
    """
    Splits, filters and merges the message history to be consumable by agents. Returns human and visualization messages.
    """
    stack: list[LangchainHumanMessage] = []
    human_messages: list[LangchainHumanMessage] = []
    visualization_messages: list[VisualizationMessage] = []

    for message in messages:
        if isinstance(message, HumanMessage):
            stack.append(LangchainHumanMessage(content=message.content))
        elif isinstance(message, VisualizationMessage) and message.answer:
            if stack:
                human_messages += merge_human_messages(stack)
                stack = []
            visualization_messages.append(message)

    if stack:
        human_messages += merge_human_messages(stack)

    return human_messages, visualization_messages
