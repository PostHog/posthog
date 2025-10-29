from typing import cast

import structlog
from langchain_core.messages import AIMessageChunk

from posthog.schema import (
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantToolCallMessage,
    AssistantUpdateEvent,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    VisualizationMessage,
)

from ee.hogai.utils.helpers import normalize_ai_message, should_output_assistant_message
from ee.hogai.utils.state import merge_message_chunk
from ee.hogai.utils.types.base import (
    AssistantDispatcherEvent,
    AssistantMessageUnion,
    AssistantResultUnion,
    MessageAction,
    MessageChunkAction,
    NodeStartAction,
)
from ee.hogai.utils.types.composed import MaxNodeName

logger = structlog.get_logger(__name__)


class AssistantStreamProcessor:
    """
    Reduces streamed actions to client-facing messages.

    The stream processor maintains state about message chains and delegates to specialized
    handlers based on action type and message characteristics.
    """

    _streaming_nodes: set[MaxNodeName]
    """Nodes that produce streaming messages."""
    _visualization_nodes: dict[MaxNodeName, type]
    """Nodes that produce visualization messages."""
    _tool_call_id_to_message: dict[str, AssistantMessage]
    """Maps tool call IDs to their parent messages for message chain tracking."""
    _streamed_update_ids: set[str]
    """Tracks the IDs of messages that have been streamed."""
    _chunks: AIMessageChunk
    """Tracks the current message chunk."""

    def __init__(
        self,
        streaming_nodes: set[MaxNodeName],
        visualization_nodes: dict[MaxNodeName, type],
    ):
        """
        Initialize the stream processor with node configuration.

        Args:
            streaming_nodes: Nodes that produce streaming messages
            visualization_nodes: Nodes that produce visualization messages
        """
        self._streaming_nodes = streaming_nodes
        self._visualization_nodes = visualization_nodes
        self._tool_call_id_to_message = {}
        self._streamed_update_ids = set()
        self._chunks = AIMessageChunk(content="")

    def process(self, event: AssistantDispatcherEvent) -> AssistantResultUnion | None:
        """
        Reduce streamed actions to client messages.

        This is the main entry point for processing actions from nodes. It delegates
        to specialized handlers based on action type and message characteristics.
        """
        action = event.action
        node_name = event.node_name

        if isinstance(action, MessageChunkAction):
            return self._handle_message_stream(action.message, cast(MaxNodeName, node_name))

        if isinstance(action, NodeStartAction):
            return AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)

        if isinstance(action, MessageAction):
            message = action.message

            # Register any tool calls for later parent chain lookups
            self._register_tool_calls(message)
            result = self._handle_message(message, cast(MaxNodeName, node_name))
            return (
                result if result is not None else AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)
            )

    def _find_parent_ids(self, message: AssistantMessage) -> tuple[str | None, str | None]:
        """
        Walk up the message chain to find the root parent's message_id and tool_call_id.

        Returns (root_message_id, root_tool_call_id) for the root message in the chain.
        Includes cycle detection and max depth protection.
        """
        root_tool_call_id = message.parent_tool_call_id
        if root_tool_call_id is None:
            return message.id, None

        root_message_id = None
        visited: set[str] = set()

        while root_tool_call_id is not None:
            if root_tool_call_id in visited:
                # Cycle detected, we skip this message
                return None, None

            visited.add(root_tool_call_id)
            parent_message = self._tool_call_id_to_message.get(root_tool_call_id)
            if parent_message is None:
                # The parent message is not registered, we skip this message as it could come
                # from a sub-nested graph invoked directly by a contextual tool.
                return None, None

            next_parent_tool_call_id = parent_message.parent_tool_call_id
            root_message_id = parent_message.id
            if next_parent_tool_call_id is None:
                return root_message_id, root_tool_call_id
            root_tool_call_id = next_parent_tool_call_id
        raise ValueError("Should not reach here")

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

    def _handle_assistant_message_with_parent(self, message: AssistantMessage) -> AssistantUpdateEvent | None:
        """Handle AssistantMessage that has a parent, creating an AssistantUpdateEvent."""
        parent_id, parent_tool_call_id = self._find_parent_ids(message)

        if parent_tool_call_id is None or parent_id is None:
            return None

        if message.content == "":
            return None

        return AssistantUpdateEvent(
            id=parent_id,
            tool_call_id=parent_tool_call_id,
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

    def _handle_message(self, message: AssistantMessageUnion, node_name: MaxNodeName) -> AssistantResultUnion | None:
        # Messages with existing IDs must be deduplicated.
        # Messages WITHOUT IDs must be streamed because they're progressive.
        if hasattr(message, "id") and message.id is not None:
            if message.id in self._streamed_update_ids:
                return None
            self._streamed_update_ids.add(message.id)

        # Root messages (no parent) are filtered by VERBOSE_NODES
        if message.parent_tool_call_id is None:
            return self._handle_root_message(message, node_name)

        # AssistantMessage with parent creates AssistantUpdateEvent
        if isinstance(message, AssistantMessage):
            return self._handle_assistant_message_with_parent(message)
        else:
            # Other message types with parents (viz, notebook, failure, tool call)
            return self._handle_special_child_message(message, node_name)

    def _handle_message_stream(self, message: AIMessageChunk, node_name: MaxNodeName) -> AssistantResultUnion | None:
        """
        Process LLM chunks from "messages" stream mode.

        With dispatch pattern, complete messages are dispatched by nodes.
        This handles AIMessageChunk for ephemeral streaming (responsiveness).
        """
        if node_name not in self._streaming_nodes:
            return None

        # Merge message chunks
        self._chunks = merge_message_chunk(self._chunks, message)

        # Stream ephemeral message (no ID = not persisted)
        return normalize_ai_message(self._chunks)
