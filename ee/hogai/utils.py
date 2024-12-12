from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Optional, TypedDict, TypeVar, Union

from jsonref import replace_refs
from langchain_core.agents import AgentAction
from langchain_core.messages import (
    HumanMessage as LangchainHumanMessage,
    merge_message_runs,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START
from pydantic import BaseModel, Field

from posthog.models.team.team import Team
from posthog.schema import (
    AssistantMessage,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    RootAssistantMessage,
    RouterMessage,
    VisualizationMessage,
)

AIMessageUnion = Union[AssistantMessage, VisualizationMessage, FailureMessage, RouterMessage, ReasoningMessage]
AssistantMessageUnion = Union[HumanMessage, AIMessageUnion]


class ConversationState(BaseModel):
    messages: list[RootAssistantMessage] = Field(..., min_length=1, max_length=50)
    id: str


class ReplaceMessages(list[AssistantMessageUnion]):
    pass


def add_messages(
    left: Sequence[AssistantMessageUnion], right: Sequence[AssistantMessageUnion]
) -> Sequence[AssistantMessageUnion]:
    if isinstance(right, ReplaceMessages):
        return list(right)
    return list(left) + list(right)


class AssistantState(TypedDict, total=False):
    messages: Annotated[Sequence[AssistantMessageUnion], add_messages]
    intermediate_steps: Optional[list[tuple[AgentAction, Optional[str]]]]
    start_id: Optional[str]
    """
    The ID of the message from which the conversation started.
    """
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
    SUMMARIZER = "summarizer"


class AssistantNode(ABC):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @abstractmethod
    def run(cls, state: AssistantState, config: RunnableConfig) -> AssistantState:
        raise NotImplementedError


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")


def filter_messages(
    messages: Sequence[AssistantMessageUnion],
    entity_filter: Union[tuple[type[AIMessageUnion], ...], type[AIMessageUnion]] = (
        AssistantMessage,
        VisualizationMessage,
    ),
) -> list[AssistantMessageUnion]:
    """
    Filters and merges the message history to be consumable by agents. Returns human and AI messages.
    """
    stack: list[LangchainHumanMessage] = []
    filtered_messages: list[AssistantMessageUnion] = []

    def _merge_stack(stack: list[LangchainHumanMessage]) -> list[HumanMessage]:
        return [
            HumanMessage(content=langchain_message.content, id=langchain_message.id)
            for langchain_message in merge_message_runs(stack)
        ]

    for message in messages:
        if isinstance(message, HumanMessage):
            stack.append(LangchainHumanMessage(content=message.content, id=message.id))
        elif isinstance(message, entity_filter):
            if stack:
                filtered_messages += _merge_stack(stack)
                stack = []
            filtered_messages.append(message)

    if stack:
        filtered_messages += _merge_stack(stack)

    return filtered_messages


T = TypeVar("T", bound=AssistantMessageUnion)


def find_last_message_of_type(messages: Sequence[AssistantMessageUnion], message_type: type[T]) -> Optional[T]:
    return next((msg for msg in reversed(messages) if isinstance(msg, message_type)), None)


def slice_messages_to_conversation_start(
    messages: Sequence[AssistantMessageUnion], start_id: Optional[str] = None
) -> Sequence[AssistantMessageUnion]:
    result = []
    for msg in messages:
        result.append(msg)
        if msg.id == start_id:
            break
    return result


def dereference_schema(schema: dict) -> dict:
    new_schema: dict = replace_refs(schema, proxies=False, lazy_load=False)
    if "$defs" in new_schema:
        new_schema.pop("$defs")
    return new_schema
