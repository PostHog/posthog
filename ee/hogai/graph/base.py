from collections.abc import Sequence
from typing import Any, Generic
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.helpers import find_last_ui_context
from ee.models import Conversation
from posthog.models import Team
from posthog.models.user import User
from posthog.schema import AssistantMessage, AssistantToolCall, MaxUIContext
from posthog.sync import database_sync_to_async

from ..graph.filter_options.types import FilterOptionsState, PartialFilterOptionsState
from ..utils.types import (
    AssistantMessageUnion,
    AssistantState,
    PartialAssistantState,
    PartialStateType,
    StateType,
)


class BaseAssistantNode(Generic[StateType, PartialStateType], AssistantContextMixin):
    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user

    async def __call__(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        """
        Run the assistant node and handle cancelled conversation before the node is run.
        """
        thread_id = (config.get("configurable") or {}).get("thread_id")
        if thread_id and await self._is_conversation_cancelled(thread_id):
            raise GenerationCanceled
        try:
            return await self.arun(state, config)
        except NotImplementedError:
            return await database_sync_to_async(self.run, thread_sensitive=False)(state, config)

    # DEPRECATED: Use `arun` instead
    def run(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        """DEPRECATED. Use `arun` instead."""
        raise NotImplementedError

    async def arun(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        raise NotImplementedError

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
        if hasattr(state, "messages"):
            return find_last_ui_context(state.messages)
        return None


AssistantNode = BaseAssistantNode[AssistantState, PartialAssistantState]
FilterOptionsBaseNode = BaseAssistantNode[FilterOptionsState, PartialFilterOptionsState]
