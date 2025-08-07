from typing import Any, Literal, TypedDict, TypeGuard, Union

from langchain_core.messages import AIMessageChunk

from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.graph.filter_options.types import FilterOptionsNodeName

# A state update can have a partial state or a LangGraph's reserved dataclasses like Interrupt.
GraphValueUpdate = dict[AssistantNodeName | FilterOptionsNodeName, dict[Any, Any] | Any]

GraphValueUpdateTuple = tuple[Literal["values"], GraphValueUpdate]


def is_value_update(update: list[Any]) -> TypeGuard[GraphValueUpdateTuple]:
    """
    Transition between nodes.

    Returns:
        PartialAssistantState, Interrupt, or other LangGraph reserved dataclasses.
    """
    return len(update) == 2 and update[0] == "updates"


def validate_value_update(
    update: GraphValueUpdate,
) -> dict[AssistantNodeName | FilterOptionsNodeName, PartialAssistantState | Any]:
    validated_update = {}
    for node_name, value in update.items():
        if isinstance(value, dict):
            validated_update[node_name] = PartialAssistantState.model_validate(value)
        else:
            validated_update[node_name] = value
    return validated_update


class LangGraphState(TypedDict):
    langgraph_node: AssistantNodeName | FilterOptionsNodeName


GraphMessageUpdateTuple = tuple[Literal["messages"], tuple[Union[AIMessageChunk, Any], LangGraphState]]


def is_message_update(update: list[Any]) -> TypeGuard[GraphMessageUpdateTuple]:
    """
    Streaming of messages.
    """
    return len(update) == 2 and update[0] == "messages"


GraphStateUpdateTuple = tuple[Literal["updates"], dict[Any, Any]]


def is_state_update(update: list[Any]) -> TypeGuard[GraphStateUpdateTuple]:
    """
    Update of the state. Returns a full state.
    """
    return len(update) == 2 and update[0] == "values"


def validate_state_update(state_update: dict[Any, Any]) -> AssistantState:
    return AssistantState.model_validate(state_update)


GraphTaskStartedUpdateTuple = tuple[Literal["debug"], tuple[Union[AIMessageChunk, Any], LangGraphState]]


def is_task_started_update(
    update: list[Any],
) -> TypeGuard[GraphTaskStartedUpdateTuple]:
    """
    Streaming of messages.
    """
    return len(update) == 2 and update[0] == "debug" and update[1]["type"] == "task"
