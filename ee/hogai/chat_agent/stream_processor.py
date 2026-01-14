from typing import Generic, cast, get_args

import structlog
from langchain_core.messages import AIMessageChunk

from posthog.schema import (
    ArtifactMessage,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantToolCall,
    AssistantUpdateEvent,
    FailureMessage,
    SubagentUpdateEvent,
)

from posthog.models import Team, User

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.chat_agent.notebook_streaming import NotebookStreamingMixin
from ee.hogai.core.stream_processor import AssistantStreamProcessorProtocol
from ee.hogai.utils.helpers import normalize_ai_message, should_output_assistant_message
from ee.hogai.utils.state import is_message_update, is_state_update, merge_message_chunk
from ee.hogai.utils.types.base import (
    ArtifactRefMessage,
    AssistantDispatcherEvent,
    AssistantGraphName,
    AssistantResultUnion,
    AssistantStreamedMessageUnion,
    BaseStateWithMessages,
    LangGraphUpdateEvent,
    MessageAction,
    MessageChunkAction,
    NodeEndAction,
    NodePath,
    NodeStartAction,
    StateType,
    UpdateAction,
)
from ee.hogai.utils.types.composed import MaxNodeName

logger = structlog.get_logger(__name__)


def find_subgraph(node_path: tuple[NodePath, ...]) -> bool:
    return bool(next((path for path in node_path if path.name in AssistantGraphName), None))


MESSAGE_TYPE_TUPLE = get_args(AssistantStreamedMessageUnion)


class BaseStreamProcessor(AssistantStreamProcessorProtocol, Generic[StateType]):
    """
    Base stream processor that reduces streamed actions to client-facing messages.
    """

    _verbose_nodes: set[MaxNodeName]
    """Nodes that emit messages."""
    _streaming_nodes: set[MaxNodeName]
    """Nodes that produce streaming messages."""
    _chunks: dict[str, AIMessageChunk]
    """Tracks the current message chunk."""
    _state: StateType | None
    """Tracks the current state."""
    _state_type: type[StateType]
    """The type of the state."""

    def __init__(
        self,
        team: Team,
        user: User,
        verbose_nodes: set[MaxNodeName],
        streaming_nodes: set[MaxNodeName],
        state_type: type[StateType],
    ):
        """
        Initialize the stream processor with node configuration.

        Args:
            team: The team
            user: The user
            verbose_nodes: Nodes that produce messages
            streaming_nodes: Nodes that produce streaming messages
            state_type: The type of the state
        """
        self._team = team
        self._user = user
        # If a node is streaming node, it should also be verbose.
        self._verbose_nodes = verbose_nodes | streaming_nodes
        self._streaming_nodes = streaming_nodes
        self._streamed_update_ids: set[str] = set()
        self._chunks = {}
        self._state_type = state_type
        self._state = None
        self._artifact_manager = ArtifactManager(self._team, self._user)

    async def process(self, event: AssistantDispatcherEvent) -> list[AssistantResultUnion] | None:
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
            return await self._handle_node_end(event, action)

        if isinstance(action, MessageChunkAction) and (results := self._handle_message_stream(event, action.message)):
            return results

        if isinstance(action, MessageAction):
            message = action.message
            if result := await self._handle_message(event, message):
                return [result]

        if isinstance(action, UpdateAction) and (update_event := self._handle_update_message(event, action)):
            return [update_event]

        return None

    async def process_langgraph_update(self, event: LangGraphUpdateEvent) -> list[AssistantResultUnion] | None:
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
            return await self.process(action)

        if is_state_update(event.update):
            new_state = self._state_type.model_validate(event.update[1])
            self._state = new_state

        return None

    async def _handle_message(
        self, action: AssistantDispatcherEvent, message: AssistantStreamedMessageUnion
    ) -> AssistantStreamedMessageUnion | None:
        """Handle a message from a node."""
        node_name = cast(MaxNodeName, action.node_name)
        produced_message: AssistantStreamedMessageUnion | None = None

        # ArtifactRefMessage must always be enriched with content, regardless of nesting level
        if isinstance(message, ArtifactRefMessage):
            try:
                enriched_message = await self._artifact_manager.aenrich_message(message)
            except (ValueError, KeyError) as e:
                logger.warning("Failed to enrich ArtifactMessage", error=str(e), artifact_id=message.artifact_id)
                enriched_message = None
            # If the message is not enriched, return None.
            if not enriched_message:
                return None
            message = enriched_message

        # Output all messages from the top-level graph.
        if not self._is_message_from_nested_node_or_graph(action.node_path or ()):
            produced_message = self._handle_root_message(message, node_name)
        # Other message types with parents (viz, notebook, failure, tool call)
        else:
            produced_message = self._handle_special_child_message(message)

        # Messages with existing IDs must be deduplicated.
        # Messages WITHOUT IDs must be streamed because they're progressive.
        if produced_message is not None and isinstance(produced_message, MESSAGE_TYPE_TUPLE):
            message_id = getattr(produced_message, "id", None)
            if not self._should_emit_message(message_id):
                return None

        return produced_message

    def _should_emit_message(self, message_id: str | None) -> bool:
        """
        Check if message should be emitted (not already streamed) and mark as streamed.

        Messages without IDs are always emitted (they're progressive streaming messages).
        Messages with IDs are deduplicated to avoid sending the same message twice.
        """
        if message_id is None:
            return True
        if message_id in self._streamed_update_ids:
            return False
        self._streamed_update_ids.add(message_id)
        return True

    def _is_message_from_nested_node_or_graph(self, node_path: tuple[NodePath, ...]) -> bool:
        """Check if the message is from a nested node or graph."""
        if not node_path:
            return False
        # The first path is always the top-level graph.
        if len(node_path) > 2:
            # The second path can is a top-level node.
            # But we have to check the next node to see if it's a nested node or graph.
            return find_subgraph(node_path[2:])

        return False

    def _handle_root_message(
        self, message: AssistantStreamedMessageUnion, node_name: MaxNodeName
    ) -> AssistantStreamedMessageUnion | None:
        """Handle messages with no parent (root messages)."""
        if node_name not in self._verbose_nodes or not should_output_assistant_message(message):
            return None
        return message

    def _handle_update_message(
        self, event: AssistantDispatcherEvent, action: UpdateAction
    ) -> AssistantUpdateEvent | SubagentUpdateEvent | None:
        """Handle AssistantMessage that has a parent, creating an AssistantUpdateEvent."""
        if not event.node_path or not action.content:
            return None

        # Find the closest tool call id to the update.
        parent_path = next((path for path in reversed(event.node_path) if path.tool_call_id), None)
        # Updates from the top-level graph nodes are not supported.
        if not parent_path:
            return None

        tool_call_id = parent_path.tool_call_id
        message_id = parent_path.message_id

        if not message_id or not tool_call_id:
            return None

        if isinstance(action.content, AssistantToolCall):
            return SubagentUpdateEvent(id=message_id, tool_call_id=tool_call_id, content=action.content)

        return AssistantUpdateEvent(id=message_id, tool_call_id=tool_call_id, content=action.content)

    def _handle_special_child_message(
        self, message: AssistantStreamedMessageUnion
    ) -> AssistantStreamedMessageUnion | None:
        """
        Handle special message types that have parents.

        These messages are returned as-is regardless of where in the nesting hierarchy they are.
        """
        # These message types are always returned as-is
        if isinstance(message, FailureMessage | ArtifactMessage):
            return message

        return None

    def _handle_message_stream(
        self, event: AssistantDispatcherEvent, message: AIMessageChunk
    ) -> list[AssistantResultUnion] | None:
        """
        Process LLM chunks from "messages" stream mode.

        With dispatch pattern, complete messages are dispatched by nodes.
        This handles AIMessageChunk for ephemeral streaming (responsiveness).

        Subclasses can override this method to add custom streaming behavior.
        """
        node_name = cast(MaxNodeName, event.node_name)
        run_id = event.node_run_id

        if node_name not in self._streaming_nodes:
            return None
        if run_id not in self._chunks:
            self._chunks[run_id] = AIMessageChunk(content="")

        # Merge message chunks
        self._chunks[run_id] = merge_message_chunk(self._chunks[run_id], message)

        # Stream ephemeral messages (no ID = not persisted).
        # normalize_ai_message() returns a list when server_tool_use blocks are present,
        # but we only stream the latest message for incremental updates
        messages = normalize_ai_message(self._chunks[run_id])
        return [messages[-1]] if messages else None

    async def _handle_node_end(
        self, event: AssistantDispatcherEvent, action: NodeEndAction
    ) -> list[AssistantResultUnion] | None:
        """Handle the end of a node. Reset the streaming chunks."""
        if not isinstance(action.state, BaseStateWithMessages):
            return None
        results: list[AssistantResultUnion] = []
        for message in action.state.messages:
            if new_event := await self.process(
                AssistantDispatcherEvent(
                    action=MessageAction(message=message),
                    node_name=event.node_name,
                    node_run_id=event.node_run_id,
                    node_path=event.node_path,
                )
            ):
                results.extend(new_event)
        return results


class ChatAgentStreamProcessor(NotebookStreamingMixin, BaseStreamProcessor[StateType]):
    """
    Stream processor for chat agents with notebook streaming support.

    This class combines the base stream processor with notebook streaming capabilities.
    Use BaseStreamProcessor directly if you don't need notebook streaming.
    """

    def _handle_message_stream(
        self, event: AssistantDispatcherEvent, message: AIMessageChunk
    ) -> list[AssistantResultUnion] | None:
        """
        Process LLM chunks with notebook streaming support.
        """
        results = super()._handle_message_stream(event, message) or []

        # Add notebook streaming results if applicable
        chunk = self._chunks.get(event.node_run_id)
        if chunk and (notebook_artifact := self._check_for_notebook_streaming(chunk)):
            results.append(notebook_artifact)

        return results if results else None
