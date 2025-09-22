from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any, Generic, Literal, Union
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import StreamWriter

from posthog.schema import AssistantMessage, AssistantToolCall, MaxBillingContext, MaxUIContext, ReasoningMessage

from posthog.models import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from ee.hogai.graph.mixins import AssistantContextMixin, ReasoningNodeMixin
from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.helpers import find_last_ui_context
from ee.hogai.utils.state import LangGraphState
from ee.hogai.utils.types import (
    AssistantMessageUnion,
    AssistantState,
    PartialAssistantState,
    PartialStateType,
    StateType,
)
from ee.hogai.utils.types.base import BaseStateWithMessages
from ee.hogai.utils.types.composed import MaxNodeName
from ee.models import Conversation


class BaseAssistantNode(Generic[StateType, PartialStateType], AssistantContextMixin, ReasoningNodeMixin, ABC):
    writer: StreamWriter | None = None
    config: RunnableConfig | None = None

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user

    @property
    @abstractmethod
    def node_name(self) -> MaxNodeName:
        raise NotImplementedError

    async def __call__(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        """
        Run the assistant node and handle cancelled conversation before the node is run.
        """
        self.config = config
        thread_id = (config.get("configurable") or {}).get("thread_id")
        if thread_id and await self._is_conversation_cancelled(thread_id):
            raise GenerationCanceled
        try:
            return await self.arun(state, config)
        except NotImplementedError:
            pass
        return await database_sync_to_async(self.run, thread_sensitive=False)(state, config)

    # DEPRECATED: Use `arun` instead
    def run(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        """DEPRECATED. Use `arun` instead."""
        raise NotImplementedError

    async def arun(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        raise NotImplementedError

    @property
    def _writer(self) -> StreamWriter | Callable[[Any], None]:
        if self.writer:
            return self.writer
        try:
            self.writer = get_stream_writer()
        except RuntimeError:
            # Not in a LangGraph context (e.g., during testing)
            def noop(*args, **kwargs):
                pass

            return noop
        return self.writer

    async def _is_conversation_cancelled(self, conversation_id: UUID) -> bool:
        conversation = await self._aget_conversation(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")
        return conversation.status == Conversation.Status.CANCELING

    def _get_tool_call(self, messages: Sequence[AssistantMessageUnion], tool_call_id: str) -> AssistantToolCall:
        for message in reversed(messages):
            if not isinstance(message, AssistantMessage) or not message.tool_calls:
                continue
            for tool_call in message.tool_calls:
                if tool_call.id == tool_call_id:
                    return tool_call
        raise ValueError(f"Tool call {tool_call_id} not found in state")

    def _get_contextual_tools(self, config: RunnableConfig) -> dict[str, Any]:
        """
        Extracts contextual tools from the runnable config.
        """
        contextual_tools = (config.get("configurable") or {}).get("contextual_tools") or {}
        if not isinstance(contextual_tools, dict):
            raise ValueError("Contextual tools must be a dictionary of tool names to tool context")
        return contextual_tools

    def _get_ui_context(self, state: StateType) -> MaxUIContext | None:
        """
        Extracts the UI context from the latest human message.
        """
        if isinstance(state, BaseStateWithMessages) and hasattr(state, "messages"):
            return find_last_ui_context(state.messages)
        return None

    def _get_billing_context(self, config: RunnableConfig) -> MaxBillingContext | None:
        """
        Extracts the billing context from the runnable config.
        """
        billing_context = (config.get("configurable") or {}).get("billing_context")
        if not billing_context:
            return None
        return MaxBillingContext.model_validate(billing_context)

    def _message_to_langgraph_update(
        self, message: AssistantMessageUnion, node_name: MaxNodeName
    ) -> tuple[tuple[()], Literal["messages"], tuple[Union[AssistantMessageUnion, Any], LangGraphState]]:
        """
        Converts an assistant message to a custom message langgraph update.
        """
        return ((), "messages", (message, {"langgraph_node": node_name}))

    async def _write_message(self, message: AssistantMessageUnion):
        """
        Writes a message to the stream writer.
        """
        if self.node_name:
            self._writer(self._message_to_langgraph_update(message, self.node_name))

    async def _write_reasoning(self, content: str, substeps: list[str] | None = None):
        """
        Streams a reasoning message to the stream writer.
        """
        await self._write_message(ReasoningMessage(content=content, substeps=substeps))


AssistantNode = BaseAssistantNode[AssistantState, PartialAssistantState]
