from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langgraph.types import StreamWriter

from posthog.schema import AssistantMessage, AssistantToolCallMessage

from ee.hogai.utils.types.base import (
    AssistantActionUnion,
    AssistantDispatcherEvent,
    AssistantMessageUnion,
    MessageAction,
)

if TYPE_CHECKING:
    from ee.hogai.utils.types.composed import MaxNodeName


class AssistantDispatcher:
    """
    Lightweight dispatcher that emits actions to LangGraph custom stream.

    Clean separation: Dispatcher dispatches, BaseAssistant reduces.

    The dispatcher does NOT update state - it just emits actions to the stream.
    """

    _parent_tool_call_id: str | None = None

    def __init__(
        self,
        writer: StreamWriter | Callable[[Any], None],
        node_name: "MaxNodeName",
        parent_tool_call_id: str | None = None,
    ):
        """
        Create a dispatcher for a specific node.

        Args:
            node_name: The name of the node dispatching actions (for attribution)
        """
        self._node_name = node_name
        self._writer = writer
        self._parent_tool_call_id = parent_tool_call_id

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
            self._writer(AssistantDispatcherEvent(action=action, node_name=self._node_name))
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
        if self._parent_tool_call_id:
            # If the dispatcher is initialized with a parent tool call id, set the parent tool call id on the message
            # This is to ensure that the message is associated with the correct tool call
            # Don't set parent_tool_call_id on:
            # 1. AssistantToolCallMessage with the same tool_call_id (to avoid self-reference)
            # 2. AssistantMessage with tool_calls containing the same ID (to avoid cycles)
            should_skip = False
            if isinstance(message, AssistantToolCallMessage) and self._parent_tool_call_id == message.tool_call_id:
                should_skip = True
            elif isinstance(message, AssistantMessage) and message.tool_calls:
                # Check if any tool call has the same ID as the parent
                for tool_call in message.tool_calls:
                    if tool_call.id == self._parent_tool_call_id:
                        should_skip = True
                        break

            if not should_skip:
                message.parent_tool_call_id = self._parent_tool_call_id
        self.dispatch(MessageAction(message=message))

    def set_as_root(self) -> None:
        """
        Set the dispatcher as the root.
        """
        self._parent_tool_call_id = None
