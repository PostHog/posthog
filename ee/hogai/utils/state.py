from typing import Any, Literal, TypedDict, TypeGuard, Union

from ee.hogai.utils.types.composed import MaxGraphState, MaxNodeName
from langchain_core.messages import AIMessageChunk

from ee.hogai.graph.taxonomy.types import TaxonomyAgentState, TaxonomyNodeName
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from structlog import get_logger

# A state update can have a partial state or a LangGraph's reserved dataclasses like Interrupt.
GraphValueUpdate = dict[MaxNodeName, dict[Any, Any] | Any]

GraphValueUpdateTuple = tuple[Literal["values"], GraphValueUpdate]

logger = get_logger(__name__)


def is_value_update(update: list[Any]) -> TypeGuard[GraphValueUpdateTuple]:
    """
    Transition between nodes.

    Returns:
        PartialAssistantState, Interrupt, or other LangGraph reserved dataclasses.
    """
    return len(update) == 2 and update[0] == "updates"


def validate_value_update(
    update: GraphValueUpdate,
) -> dict[MaxNodeName, MaxGraphState | Any]:
    validated_update: dict[MaxNodeName, MaxGraphState | Any] = {}
    for node_name, value in update.items():
        if isinstance(value, dict):
            if isinstance(node_name, TaxonomyNodeName):
                validated_update[node_name] = TaxonomyAgentState.model_validate(value)
            else:
                validated_update[node_name] = PartialAssistantState.model_validate(value)
        else:
            validated_update[node_name] = value
    return validated_update


class LangGraphState(TypedDict):
    langgraph_node: MaxNodeName


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


def prepare_reasoning_progress_message(content: str) -> AIMessageChunk:
    """Display progress as a reasoning message"""
    if not content:
        logger.warning("Content is required to prepare a reasoning progress message")
    elif len(content) > 200:
        logger.warning("Content is too long to prepare a reasoning progress message", extra={"content": content})
        content = content[:200] + "..."
    # What we're doing here is emitting an AIMessageChunk that mimics the OpenAI reasoning format
    # This gets rendered as a ReasoningMessage in the Assistant class
    # It's a roundabout way of returning a ReasoningMessage, but otherwise we'd have to make larger changes to Assistant
    return AIMessageChunk(
        content="",
        additional_kwargs={"reasoning": {"summary": [{"text": f"**{content}**"}]}},
    )
