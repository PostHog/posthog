from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import StreamWriter

from ee.hogai.utils.types.base import (
    AssistantActionUnion,
    AssistantDispatcherEvent,
    AssistantMessageUnion,
    MessageAction,
    NodePath,
    UpdateAction,
)


class AssistantDispatcher:
    """
    Lightweight dispatcher that emits actions to LangGraph custom stream.

    Clean separation: Dispatcher dispatches, BaseAssistant reduces.

    The dispatcher does NOT update state - it just emits actions to the stream.
    """

    _node_path: tuple[NodePath, ...]

    def __init__(
        self,
        writer: StreamWriter | Callable[[Any], None],
        node_path: tuple[NodePath, ...],
        node_name: str,
        node_run_id: str,
    ):
        """
        Create a dispatcher for a specific node.

        Args:
            node_name: The name of the node dispatching actions (for attribution)
        """
        self._writer = writer
        self._node_path = node_path
        self._node_name = node_name
        self._node_run_id = node_run_id

    def dispatch(self, action: AssistantActionUnion) -> None:
        """
        Emit action to custom stream. Does NOT update state.

        The action is forwarded to BaseAssistant._reduce_action() which:
        1. Calls aupdate_state() to persist the change
        2. Yields the message to the client

        Args:
            action: Action dict with "type" and "payload" keys
        """
        try:
            self._writer(
                AssistantDispatcherEvent(
                    action=action, node_path=self._node_path, node_name=self._node_name, node_run_id=self._node_run_id
                )
            )
        except Exception as e:
            # Log error but don't crash node execution
            # The dispatcher should be resilient to writer failures
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to dispatch action: {e}", exc_info=True)

    def message(self, message: AssistantMessageUnion) -> None:
        """
        Dispatch a message to the stream.
        """
        self.dispatch(MessageAction(message=message))

    def update(self, content: str):
        """Dispatch a transient update message to the stream that will be associated with a tool call in the UI."""
        self.dispatch(UpdateAction(content=content))


def create_dispatcher_from_config(config: RunnableConfig, node_path: tuple[NodePath, ...]) -> AssistantDispatcher:
    """Create a dispatcher from a RunnableConfig and node path"""
    # Set writer from LangGraph context
    try:
        writer = get_stream_writer()
    except RuntimeError:
        # Not in streaming context (e.g., testing)
        # Use noop writer
        def noop(*_args, **_kwargs):
            pass

        writer = noop

    metadata = config.get("metadata") or {}
    node_name: str = metadata.get("langgraph_node") or ""
    # `langgraph_checkpoint_ns` contains the nested path to the node, so it's more accurate for streaming.
    node_run_id: str = metadata.get("langgraph_checkpoint_ns") or ""

    return AssistantDispatcher(writer, node_path=node_path, node_run_id=node_run_id, node_name=node_name)
