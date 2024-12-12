from collections.abc import Sequence
from typing import Annotated, Any, Literal, Optional, TypedDict, TypeGuard, Union

from langchain_core.agents import AgentAction
from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel, Field

from posthog.schema import (
    AssistantMessage,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    RouterMessage,
    VisualizationMessage,
)

from .types import AssistantNodeName

AIMessageUnion = Union[AssistantMessage, VisualizationMessage, FailureMessage, RouterMessage, ReasoningMessage]
AssistantMessageUnion = Union[HumanMessage, AIMessageUnion]


class ReplaceMessages(list[AssistantMessageUnion]):
    pass


def add_messages(
    left: Sequence[AssistantMessageUnion], right: Sequence[AssistantMessageUnion]
) -> Sequence[AssistantMessageUnion]:
    if isinstance(right, ReplaceMessages):
        return list(right)
    return list(left) + list(right)


class _SharedAssistantState(BaseModel):
    intermediate_steps: Optional[list[tuple[AgentAction, Optional[str]]]] = Field(default=None)
    start_id: Optional[str] = Field(default=None)
    """
    The ID of the message from which the conversation started.
    """
    plan: Optional[str] = Field(default=None)


class AssistantState(_SharedAssistantState):
    messages: Annotated[Sequence[AssistantMessageUnion], add_messages]


class PartialAssistantState(_SharedAssistantState):
    messages: Optional[Annotated[Sequence[AssistantMessageUnion], add_messages]] = Field(default=None)


# A state update can have a partial state or a LangGraph's reserved dataclasses like Interrupt.
GraphValueUpdate = dict[AssistantNodeName, dict | Any]

GraphValueUpdateTuple = tuple[Literal["values"], GraphValueUpdate]


def is_value_update(update: list[Any]) -> TypeGuard[GraphValueUpdateTuple]:
    """
    Transition between nodes.

    Returns:
        PartialAssistantState, Interrupt, or other LangGraph reserved dataclasses.
    """
    return len(update) == 2 and update[0] == "updates"


def validate_value_update(update: GraphValueUpdate) -> dict[AssistantNodeName | Any]:
    validated_update: dict[AssistantNodeName | Any] = {}
    for node_name, value in update.items():
        if isinstance(value, dict):
            validated_update[node_name] = PartialAssistantState.model_validate(value)
        else:
            validated_update[node_name] = value
    return validated_update


class LangGraphState(TypedDict):
    langgraph_node: AssistantNodeName


GraphMessageUpdate = tuple[Literal["messages"], tuple[Union[AIMessageChunk, Any], LangGraphState]]


def is_message_update(update: list[Any]) -> TypeGuard[GraphMessageUpdate]:
    """
    Streaming of messages.
    """
    return len(update) == 2 and update[0] == "messages"


GraphStateUpdate = tuple[Literal["updates"], dict]


def is_state_update(update: list[Any]) -> TypeGuard[GraphStateUpdate]:
    """
    Update of the state. Returns a full state.
    """
    return len(update) == 2 and update[0] == "values"


def validate_state_update(state_update: dict) -> AssistantState:
    return AssistantState.model_validate(state_update)


GraphTaskStartedUpdate = tuple[Literal["debug"], tuple[Union[AIMessageChunk, Any], LangGraphState]]


def is_task_started_update(
    update: list[Any],
) -> TypeGuard[GraphTaskStartedUpdate]:
    """
    Streaming of messages.
    """
    return len(update) == 2 and update[0] == "debug" and update[1]["type"] == "task"
