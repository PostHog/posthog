import json
import operator
from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Any, Optional, TypedDict, Union

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
    TRENDS_PLANNER = "trends_planner"
    TRENDS_PLANNER_TOOLS = "trends_planner_tools"
    TRENDS_GENERATOR = "trends_generator"
    TRENDS_GENERATOR_TOOLS = "trends_generator_tools"
    FUNNEL_PLANNER = "funnel_planner"
    FUNNEL_PLANNER_TOOLS = "funnel_planner_tools"
    FUNNEL_GENERATOR = "funnel_generator"
    FUNNEL_GENERATOR_TOOLS = "funnel_generator_tools"


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


def replace_value_in_dict(item: Any, original_schema: Any):
    if isinstance(item, list):
        return [replace_value_in_dict(i, original_schema) for i in item]
    elif isinstance(item, dict):
        if list(item.keys()) == ["$ref"]:
            definitions = item["$ref"][2:].split("/")
            res = original_schema.copy()
            for definition in definitions:
                res = res[definition]
            return res
        else:
            return {key: replace_value_in_dict(i, original_schema) for key, i in item.items()}
    else:
        return item


def flatten_schema(schema: dict):
    for _ in range(100):
        if "$ref" not in json.dumps(schema):
            break
        schema = replace_value_in_dict(schema.copy(), schema.copy())
    del schema["$defs"]
    return schema
