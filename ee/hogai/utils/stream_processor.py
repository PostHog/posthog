from typing import Protocol, cast, get_args

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
from ee.hogai.utils.state import is_message_update, merge_message_chunk
from ee.hogai.utils.types.base import (
    AssistantDispatcherEvent,
    AssistantMessageUnion,
    AssistantResultUnion,
    BaseStateWithMessages,
    LangGraphUpdateEvent,
    MessageAction,
    MessageChunkAction,
    NodeEndAction,
    NodePath,
    NodeStartAction,
)
from ee.hogai.utils.types.composed import MaxNodeName

logger = structlog.get_logger(__name__)


class AssistantStreamProcessorProtocol(Protocol):
    """Protocol defining the interface for assistant stream processors."""

    _streamed_update_ids: set[str]
    """Tracks the IDs of messages that have been streamed."""

    def process(self, event: AssistantDispatcherEvent) -> list[AssistantResultUnion] | None:
        """Process a dispatcher event and return a result or None."""
        ...

    def process_langgraph_update(self, event: LangGraphUpdateEvent) -> list[AssistantResultUnion] | None:
        """Process a LangGraph update event and return a list of results or None."""
        ...

    def mark_id_as_streamed(self, message_id: str) -> None:
        """Mark a message ID as streamed."""
        self._streamed_update_ids.add(message_id)


class AssistantStreamProcessor(AssistantStreamProcessorProtocol):
    """
    Reduces streamed actions to client-facing messages.

    The stream processor maintains state about message chains and delegates to specialized
    handlers based on action type and message characteristics.
    """

    _verbose_nodes: set[MaxNodeName]
    """Nodes that emit messages."""
    _streaming_nodes: set[MaxNodeName]
    """Nodes that produce streaming messages."""
    _tool_call_id_to_message: dict[str, AssistantMessage]
    """Maps tool call IDs to their parent messages for message chain tracking."""
    _chunks: dict[str, AIMessageChunk]
    """Tracks the current message chunk."""

    def __init__(self, verbose_nodes: set[MaxNodeName], streaming_nodes: set[MaxNodeName]):
        """
        Initialize the stream processor with node configuration.

        Args:
            verbose_nodes: Nodes that produce messages
            streaming_nodes: Nodes that produce streaming messages
        """
        # If a node is streaming node, it should also be verbose.
        self._verbose_nodes = verbose_nodes | streaming_nodes
        self._streaming_nodes = streaming_nodes
        self._tool_call_id_to_message = {}
        self._streamed_update_ids = set()
        self._chunks = {}

    def process(self, event: AssistantDispatcherEvent) -> list[AssistantResultUnion] | None:
        """
        Reduce streamed actions to client messages.

        This is the main entry point for processing actions from nodes. It delegates
        to specialized handlers based on action type and message characteristics.
        """
        action = event.action

        if isinstance(action, NodeStartAction):
            self._chunks[event.node_run_id] = AIMessageChunk(content="")
            return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)]

        if isinstance(action, NodeEndAction):
            if event.node_run_id in self._chunks:
                del self._chunks[event.node_run_id]
            return self._handle_node_end(event, action)

        if isinstance(action, MessageChunkAction) and (result := self._handle_message_stream(event, action.message)):
            return [result]

        if isinstance(action, MessageAction):
            message = action.message
            if result := self._handle_message(event, message):
                return [result]

        return None

    def process_langgraph_update(self, event: LangGraphUpdateEvent) -> list[AssistantResultUnion] | None:
        """
        Process a LangGraph update event.
        """
        if is_message_update(event.update):
            # Convert the message chunk update to a dispatcher event to prepare for a bright future without LangGraph
            maybe_message_chunk, state = event.update[1]
            if not isinstance(maybe_message_chunk, AIMessageChunk):
                return None
            action = AssistantDispatcherEvent(
                action=MessageChunkAction(message=maybe_message_chunk),
                node_name=state["langgraph_node"],
                node_run_id=state["langgraph_checkpoint_ns"],
            )
            return self.process(action)

        return None

    def _handle_message(
        self, action: AssistantDispatcherEvent, message: AssistantMessageUnion
    ) -> AssistantResultUnion | None:
        node_name = cast(MaxNodeName, action.node_name)

        # Set the parent tool call id on the message if it's required,
        # so the frontend can properly display the message chain.
        message = self._set_message_parent_id(message, action.node_path)
        produced_message: AssistantResultUnion | None = None

        # Root messages (no parent)
        if message.parent_tool_call_id is None:
            produced_message = self._handle_root_message(message, node_name)
        # AssistantMessage with parent creates AssistantUpdateEvent
        elif isinstance(message, AssistantMessage):
            produced_message = self._handle_assistant_message_with_parent(action, message)
        # Other message types with parents (viz, notebook, failure, tool call)
        else:
            produced_message = self._handle_special_child_message(message, node_name)

        # Messages with existing IDs must be deduplicated.
        # Messages WITHOUT IDs must be streamed because they're progressive.
        if isinstance(produced_message, get_args(AssistantMessageUnion)) and message.id is not None:
            if message.id in self._streamed_update_ids:
                return None
            self._streamed_update_ids.add(message.id)

        return produced_message

    def _handle_root_message(
        self, message: AssistantMessageUnion, node_name: MaxNodeName
    ) -> AssistantMessageUnion | None:
        """Handle messages with no parent (root messages)."""
        if node_name not in self._verbose_nodes or not should_output_assistant_message(message):
            return None
        return message

    def _handle_assistant_message_with_parent(
        self, event: AssistantDispatcherEvent, message: AssistantMessage
    ) -> AssistantUpdateEvent | None:
        """Handle AssistantMessage that has a parent, creating an AssistantUpdateEvent."""
        if not event.node_path or not message.content:
            return None

        last_path = event.node_path[-1]
        message_id = last_path.message_id
        tool_call_id = last_path.tool_call_id

        if not message_id or not tool_call_id:
            return None

        return AssistantUpdateEvent(id=message_id, tool_call_id=tool_call_id, content=message.content)

    def _handle_special_child_message(
        self, message: AssistantMessageUnion, node_name: MaxNodeName
    ) -> AssistantMessageUnion | None:
        """
        Handle special message types that have parents.

        These messages are returned as-is regardless of where in the nesting hierarchy they are.
        """
        # These message types are always returned as-is
        if isinstance(message, VisualizationMessage | MultiVisualizationMessage) or isinstance(
            message, NotebookUpdateMessage | FailureMessage
        ):
            return message

        if isinstance(message, AssistantToolCallMessage):
            # No need to yield tool call messages not at the root level
            return None

        # Should not reach here
        raise ValueError(f"Unhandled special message type: {type(message).__name__}")

    def _handle_message_stream(
        self, event: AssistantDispatcherEvent, message: AIMessageChunk
    ) -> AssistantResultUnion | None:
        """
        Process LLM chunks from "messages" stream mode.

        With dispatch pattern, complete messages are dispatched by nodes.
        This handles AIMessageChunk for ephemeral streaming (responsiveness).
        """
        node_name = cast(MaxNodeName, event.node_name)
        run_id = event.node_run_id

        if node_name not in self._streaming_nodes:
            return None
        if run_id not in self._chunks:
            self._chunks[run_id] = AIMessageChunk(content="")

        # Merge message chunks
        self._chunks[run_id] = merge_message_chunk(self._chunks[run_id], message)

        # Stream ephemeral message (no ID = not persisted)
        return normalize_ai_message(self._chunks[run_id])

    def _handle_node_end(
        self, event: AssistantDispatcherEvent, action: NodeEndAction
    ) -> list[AssistantResultUnion] | None:
        if not isinstance(action.state, BaseStateWithMessages):
            return None
        results: list[AssistantResultUnion] = []
        for message in action.state.messages:
            if new_event := self.process(
                AssistantDispatcherEvent(
                    action=MessageAction(message=message),
                    node_name=event.node_name,
                    node_run_id=event.node_run_id,
                    node_path=event.node_path,
                )
            ):
                results.extend(new_event)
        return results

    def _set_message_parent_id(
        self, message: AssistantMessageUnion, node_path: tuple[NodePath, ...] | None = None
    ) -> AssistantMessageUnion:
        """Associate a message with the parent tool call."""
        # No path – stream all messages.
        if not node_path:
            return message

        parent_tool_call_id = node_path[-1].tool_call_id

        # If the dispatcher is initialized with a parent tool call id, set the parent tool call id on the message
        # This is to ensure that the message is associated with the correct tool call
        # Don't set parent_tool_call_id on:
        # 1. AssistantToolCallMessage with the same tool_call_id (to avoid self-reference)
        # 2. AssistantMessage with tool_calls containing the same ID (to avoid cycles)
        should_skip = False
        if isinstance(message, AssistantToolCallMessage) and parent_tool_call_id == message.tool_call_id:
            should_skip = True
        elif isinstance(message, AssistantMessage) and message.tool_calls:
            # Check if any tool call has the same ID as the parent
            for tool_call in message.tool_calls:
                if tool_call.id == parent_tool_call_id:
                    should_skip = True
                    break
        if not should_skip:
            message.parent_tool_call_id = parent_tool_call_id

        return message
