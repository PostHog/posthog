"""
Message dispatcher for the AI assistant.

This module implements the dispatch/reducer pattern for managing assistant state updates.
All state changes go through the dispatcher → reducer flow for consistency and exception safety.
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
        if self._parent_tool_call_id:
            if not isinstance(message, AssistantToolCallMessage) or self._parent_tool_call_id != message.id:
                message.parent_tool_call_id = self._parent_tool_call_id
        self.dispatch(MessageAction(message=message))

    def node_start(self) -> None:
        """
        Dispatch a node start action to the stream.
        """
        self.dispatch(NodeStartAction())
