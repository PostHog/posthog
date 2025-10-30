from typing import Any, Literal, TypedDict, TypeGuard, Union

from langchain_core.messages import AIMessageChunk
from structlog import get_logger

from ee.hogai.graph.deep_research.types import DeepResearchNodeName, PartialDeepResearchState
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState, TaxonomyNodeName
from ee.hogai.utils.types.base import PartialAssistantState
from ee.hogai.utils.types.composed import AssistantMaxGraphState, AssistantMaxPartialGraphState, MaxNodeName

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
) -> dict[MaxNodeName, AssistantMaxPartialGraphState | Any]:
    validated_update: dict[MaxNodeName, AssistantMaxPartialGraphState | Any] = {}
    for node_name, value in update.items():
        if isinstance(value, dict):
            if isinstance(node_name, TaxonomyNodeName):
                validated_update[node_name] = TaxonomyAgentState.model_validate(value)
            elif isinstance(node_name, DeepResearchNodeName):
                validated_update[node_name] = PartialDeepResearchState.model_validate(value)
            else:
                validated_update[node_name] = PartialAssistantState.model_validate(value)
        else:
            validated_update[node_name] = value
    return validated_update


class LangGraphState(TypedDict):
    langgraph_node: MaxNodeName
    checkpoint_ns: str


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


def validate_state_update(
    state_update: dict[Any, Any], state_class: type[AssistantMaxGraphState]
) -> AssistantMaxGraphState:
    return state_class.model_validate(state_update)


GraphTaskStartedUpdateTuple = tuple[Literal["debug"], tuple[Union[AIMessageChunk, Any], LangGraphState]]


def is_task_started_update(
    update: list[Any],
) -> TypeGuard[GraphTaskStartedUpdateTuple]:
    """
    Streaming of messages.
    """
    return len(update) == 2 and update[0] == "debug" and update[1]["type"] == "task"


def prepare_reasoning_progress_message(content: str) -> str | None:
    """Display progress as a reasoning message"""
    if not content:
        logger.warning("Content is required to prepare a reasoning progress message")
        return None
    elif len(content) > 200:
        logger.warning("Content is too long to prepare a reasoning progress message", extra={"content": content})
        content = content[:200] + "..."
    return content


def merge_message_chunk(existing_chunk: AIMessageChunk, new_chunk: AIMessageChunk) -> AIMessageChunk:
    """Merge a new message chunk with existing chunks, handling content format compatibility.

    # This is because we reset to AIMessageChunk(content="") in a few places,
    # but if we're switching between reasoning and non-reasoning models between different nodes,
    # the format of the content will change, and we need to reset the chunks to the right format.
    """

    current_is_list = isinstance(existing_chunk.content, list)
    new_is_list = isinstance(new_chunk.content, list)

    if current_is_list != new_is_list:
        # Content types are incompatible - reset with new chunk
        existing_chunk = new_chunk
    else:
        # Compatible types - merge normally
        existing_chunk += new_chunk  # type: ignore

    return existing_chunk
