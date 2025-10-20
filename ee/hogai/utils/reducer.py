"""
Message reducer for the AI assistant.

This module implements the reducer side of the dispatch/reducer pattern.
The reducer processes actions from the dispatcher and determines what messages
should be sent to the client.
"""

import structlog

from posthog.schema import (
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantToolCallMessage,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    UpdateMessage,
    VisualizationMessage,
)

from ee.hogai.utils.dispatcher import ActionType
from ee.hogai.utils.helpers import should_output_assistant_message
from ee.hogai.utils.state import GraphDispatcherActionUpdateTuple
from ee.hogai.utils.types.base import AssistantMessageOrStatusUnion, AssistantMessageUnion
from ee.hogai.utils.types.composed import MaxNodeName

logger = structlog.get_logger(__name__)


class AssistantMessageReducer:
    """
    Reduces dispatcher actions to client-facing messages.

    The reducer maintains state about message chains and delegates to specialized
    handlers based on action type and message characteristics.
    """

    def __init__(
        self,
        visualization_nodes: dict[MaxNodeName, type],
    ):
        """
        Initialize the reducer with node configuration.

        Args:
            visualization_nodes: Nodes that produce visualization messages
        """
        self._visualization_nodes = visualization_nodes

        # State
        self._tool_call_id_to_message: dict[str, AssistantMessage] = {}
        """Maps tool call IDs to their parent messages for message chain tracking."""

    def _find_parent_ids(self, message: AssistantMessage) -> tuple[str | None, str | None]:
        """
        Walk up the message chain to find the root parent's tool_call_id and message_id.

        Returns (message_id, parent_tool_call_id) for the root message in the chain.
        Includes cycle detection and max depth protection.
        """
        MAX_DEPTH = 100
        parent_tool_call_id = message.parent_tool_call_id
        message_id = None
        visited: set[str] = set()
        depth = 0

        while parent_tool_call_id is not None:
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError(f"Message chain exceeded maximum depth of {MAX_DEPTH}.")

            if parent_tool_call_id in visited:
                raise ValueError(f"Cycle detected in message chain at tool_call_id {parent_tool_call_id}.")

            visited.add(parent_tool_call_id)
            parent_message = self._tool_call_id_to_message.get(parent_tool_call_id)
            if parent_message is None:
                # The parent message is not registered, we skip this message as it could come
                # from a sub-nested graph invoked directly by a contextual tool.
                return None, None

            next_parent_tool_call_id = parent_message.parent_tool_call_id
            message_id = parent_message.id
            if next_parent_tool_call_id is None:
                return message_id, parent_tool_call_id
            parent_tool_call_id = next_parent_tool_call_id
        return message_id, parent_tool_call_id

    def _register_tool_calls(self, message: AssistantMessageUnion) -> None:
        """Register any tool calls in the message for later lookup."""
        if isinstance(message, AssistantMessage) and message.tool_calls is not None:
            for tool_call in message.tool_calls:
                self._tool_call_id_to_message[tool_call.id] = message

    def _handle_root_message(
        self, message: AssistantMessageUnion, node_name: MaxNodeName
    ) -> AssistantMessageUnion | None:
        """Handle messages with no parent (root messages)."""
        if not should_output_assistant_message(message):
            return None
        return message

    def _handle_assistant_message_with_parent(self, message: AssistantMessage) -> UpdateMessage | None:
        """Handle AssistantMessage that has a parent, creating an UpdateMessage."""
        parent_id, parent_tool_call_id = self._find_parent_ids(message)

        if parent_tool_call_id is None or parent_id is None:
            return None

        return UpdateMessage(
            id=parent_id,
            parent_tool_call_id=parent_tool_call_id,
            content=message.content,
        )

    def _handle_special_child_message(
        self, message: AssistantMessageUnion, node_name: MaxNodeName
    ) -> AssistantMessageUnion | None:
        """
        Handle special message types that have parents.

        These messages are returned as-is regardless of where in the nesting hierarchy they are.
        """
        # Return visualization messages only if from visualization nodes
        if isinstance(message, VisualizationMessage | MultiVisualizationMessage):
            if node_name in self._visualization_nodes:
                return message
            return None

        # These message types are always returned as-is
        if isinstance(message, NotebookUpdateMessage | FailureMessage):
            return message

        if isinstance(message, AssistantToolCallMessage):
            # No need to yield tool call messages not at the root level
            return None

        # Should not reach here
        raise ValueError(f"Unhandled special message type: {type(message).__name__}")

    def _handle_message(self, message: AssistantMessageUnion, node_name: MaxNodeName) -> AssistantMessageUnion | None:
        # Root messages (no parent) are filtered by VERBOSE_NODES
        if message.parent_tool_call_id is None:
            return self._handle_root_message(message, node_name)

        # AssistantMessage with parent creates UpdateMessage
        if isinstance(message, AssistantMessage):
            return self._handle_assistant_message_with_parent(message)
        else:
            # Other message types with parents (viz, notebook, failure, tool call)
            return self._handle_special_child_message(message, node_name)

    def reduce(self, update: GraphDispatcherActionUpdateTuple) -> AssistantMessageOrStatusUnion | None:
        """
        Reduce dispatcher actions to client messages.

        This is the main entry point for processing actions from nodes. It delegates
        to specialized handlers based on action type and message characteristics.
        """
        event, state = update[1]
        action = event.action
        node_name = state["langgraph_node"]

        # Handle NODE_START actions
        if action.type == ActionType.NODE_START:
            return AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)

        # Handle MESSAGE actions
        elif action.type == ActionType.MESSAGE:
            message = action.message

            # Register any tool calls for later parent chain lookups
            self._register_tool_calls(message)
            result = self._handle_message(message, node_name)
            return (
                result if result is not None else AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)
            )
