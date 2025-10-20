"""
Message dispatcher for the AI assistant.

This module implements the dispatch/reducer pattern for managing assistant message updates.
"""

from collections.abc import Callable
from enum import StrEnum
from typing import Any, Literal

from langgraph.types import StreamWriter
from pydantic import BaseModel, Field

from posthog.schema import AssistantToolCallMessage

from ee.hogai.utils.types.base import AssistantMessageUnion


class ActionType(StrEnum):
    """
    Action types for state updates.

    All state changes (messages and routing fields) go through dispatch.
    """

    MESSAGE = "MESSAGE"
    NODE_START = "NODE_START"


class MessageAction(BaseModel):
    type: Literal[ActionType.MESSAGE] = ActionType.MESSAGE
    message: AssistantMessageUnion


class NodeStartAction(BaseModel):
    type: Literal[ActionType.NODE_START] = ActionType.NODE_START


AssistantActionUnion = MessageAction | NodeStartAction


class AssistantDispatcherEvent(BaseModel):
    action: AssistantActionUnion = Field(discriminator="type")


class AssistantDispatcher:
    """
    Lightweight dispatcher that emits actions to LangGraph custom stream.

    Clean separation: Dispatcher dispatches, BaseAssistant reduces.

    The dispatcher does NOT update state - it just emits actions to the stream.
    """

    _parent_tool_call_id: str | None = None

    def __init__(self, node_name: str, parent_tool_call_id: str | None = None):
        """
        Create a dispatcher for a specific node.

        Args:
            node_name: The name of the node dispatching actions (for attribution)
        """
        self._node_name = node_name
        self._writer: StreamWriter | Callable[[Any], None] | None = None
        self._parent_tool_call_id = parent_tool_call_id

    def set_writer(self, writer: StreamWriter | Callable[[Any], None]) -> None:
        """
        Set the stream writer from LangGraph context.

        Args:
            writer: The LangGraph stream writer or a callable (noop for testing)
        """
        self._writer = writer

    def dispatch(self, action: AssistantActionUnion) -> None:
        """
        Emit action to custom stream. Does NOT update state.

        The action is forwarded to BaseAssistant._reduce_action() which:
        1. Calls aupdate_state() to persist the change
        2. Yields the message to the client

        Args:
            action: Action dict with "type" and "payload" keys
        """
        if not self._writer:
            return  # No writer (e.g., testing without streaming)

        # Emit via LangGraph custom stream
        self._writer(((), "action", (AssistantDispatcherEvent(action=action), {"langgraph_node": self._node_name})))

    def message(self, message: AssistantMessageUnion) -> None:
        """
        Dispatch a message to the stream.
        """
        from posthog.schema import AssistantMessage as SchemaAssistantMessage

        if self._parent_tool_call_id:
            # If the dispatcher is initialized with a parent tool call id, set the parent tool call id on the message
            # This is to ensure that the message is associated with the correct tool call
            # Don't set parent_tool_call_id on:
            # 1. AssistantToolCallMessage with the same tool_call_id (to avoid self-reference)
            # 2. AssistantMessage with tool_calls containing the same ID (to avoid cycles)
            should_skip = False
            if isinstance(message, AssistantToolCallMessage) and self._parent_tool_call_id == message.tool_call_id:
                should_skip = True
            elif isinstance(message, SchemaAssistantMessage) and message.tool_calls:
                # Check if any tool call has the same ID as the parent
                for tool_call in message.tool_calls:
                    if tool_call.id == self._parent_tool_call_id:
                        should_skip = True
                        break

            if not should_skip:
                message.parent_tool_call_id = self._parent_tool_call_id
        self.dispatch(MessageAction(message=message))

    def node_start(self) -> None:
        """
        Dispatch a node start action to the stream.
        """
        self.dispatch(NodeStartAction())
