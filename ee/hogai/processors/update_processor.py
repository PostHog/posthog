"""
Protocol and base implementation for graph-specific update processing.

This module defines the interface that graphs implement to handle their own
update logic, removing the need for centralized if/else chains in Assistant.
"""

from abc import ABC, abstractmethod
from typing import Optional, Protocol, TypeVar, Generic
from pydantic import BaseModel
from langchain_core.messages import AIMessageChunk

from ee.hogai.utils.state import (
    GraphMessageUpdateTuple,
    GraphValueUpdateTuple,
    validate_value_update,
)
from ee.hogai.utils.helpers import extract_content_from_ai_message, should_output_assistant_message
from ee.hogai.utils.types import AssistantNodeName, BaseState
from ee.hogai.graph.filter_options.types import FilterOptionsNodeName
from posthog.schema import (
    ReasoningMessage,
    AssistantMessage,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
)


StateT = TypeVar("StateT", bound=BaseState)


class GraphUpdateProcessor(Protocol[StateT]):
    """Protocol for graph-specific update processing."""

    def process_value_update(self, update: GraphValueUpdateTuple) -> list[BaseModel] | None:
        """Process value updates specific to this graph's nodes."""
        ...

    def process_message_update(self, update: GraphMessageUpdateTuple) -> BaseModel | None:
        """Process message streaming updates for this graph's nodes."""
        ...

    async def get_reasoning_message(
        self, node_name: AssistantNodeName | FilterOptionsNodeName, state: StateT
    ) -> Optional[ReasoningMessage]:
        """Generate reasoning messages for this graph's nodes."""
        ...


class BaseGraphUpdateProcessor(ABC, Generic[StateT]):
    """Base implementation of graph update processing."""

    def __init__(self, team, user):
        self._team = team
        self._user = user

    @abstractmethod
    async def get_reasoning_message(
        self, node_name: AssistantNodeName | FilterOptionsNodeName, state: StateT
    ) -> Optional[ReasoningMessage]:
        """Generate reasoning messages specific to this graph's nodes."""
        pass

    @property
    def visualization_nodes(self) -> set[AssistantNodeName]:
        """Nodes that generate visualizations - override in subclasses."""
        return set()

    @property
    def verbose_nodes(self) -> set[AssistantNodeName | FilterOptionsNodeName]:
        """Nodes that can send messages to the client - override in subclasses."""
        return set()

    @property
    def streaming_nodes(self) -> set[AssistantNodeName | FilterOptionsNodeName]:
        """Nodes that can stream messages to the client - override in subclasses."""
        return set()

    def process_value_update(self, update: GraphValueUpdateTuple) -> list[BaseModel] | None:
        """Common implementation for value updates."""
        _, maybe_state_update = update
        state_update = validate_value_update(maybe_state_update)

        # Handle visualization nodes (if any)
        if self.visualization_nodes and (intersected_nodes := state_update.keys() & self.visualization_nodes):
            node_name = intersected_nodes.pop()
            node_val = state_update[node_name]
            if hasattr(node_val, "messages") and node_val.messages:
                return list(node_val.messages)
            elif hasattr(node_val, "intermediate_steps") and node_val.intermediate_steps:
                return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)]

        # Handle verbose nodes
        for node_name in self.verbose_nodes:
            if node_val := state_update.get(node_name):
                if hasattr(node_val, "messages") and node_val.messages:
                    messages = []
                    for candidate_message in node_val.messages:
                        if should_output_assistant_message(candidate_message):
                            messages.append(candidate_message)
                    if messages:
                        return messages

        return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)]

    def process_message_update(self, update: GraphMessageUpdateTuple) -> BaseModel | None:
        """Common implementation for message updates."""
        langchain_message, langgraph_state = update[1]
        if not isinstance(langchain_message, AIMessageChunk):
            return None

        node_name = langgraph_state.get("langgraph_node")
        if not node_name or node_name not in self.streaming_nodes:
            return None

        # Extract content from the message chunk
        message_content = extract_content_from_ai_message(langchain_message)
        if not message_content:
            return None

        return AssistantMessage(content=message_content)
