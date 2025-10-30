from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Generic
from uuid import UUID

from django.conf import settings

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.context import AssistantContextManager
from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.utils.dispatcher import AssistantDispatcher
from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.helpers import find_start_message
from ee.hogai.utils.types.base import (
    AssistantMessageUnion,
    AssistantState,
    PartialAssistantState,
    PartialStateType,
    StateType,
)
from ee.models import Conversation

if TYPE_CHECKING:
    from ee.hogai.utils.types.composed import MaxNodeName


class BaseAssistantNode(Generic[StateType, PartialStateType], AssistantContextMixin, ABC):
    _config: RunnableConfig | None = None
    _context_manager: AssistantContextManager | None = None
    _dispatcher: AssistantDispatcher | None = None
    _parent_tool_call_id: str | None = None

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user

    @property
    @abstractmethod
    def node_name(self) -> "MaxNodeName":
        raise NotImplementedError

    async def __call__(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        """
        Run the assistant node and handle cancelled conversation before the node is run.
        """
        # Reset the context manager and dispatcher on a new run
        self._context_manager = None
        self._dispatcher = None
        self._config = config

        if isinstance(state, AssistantState) and state.root_tool_call_id:
            # NOTE: we set the parent tool call id as the root tool call id
            # This will be deprecated once all tools become MaxTools and are removed from the graph
            self._parent_tool_call_id = state.root_tool_call_id

        self.dispatcher.node_start()

        thread_id = (config.get("configurable") or {}).get("thread_id")
        if thread_id and await self._is_conversation_cancelled(thread_id):
            raise GenerationCanceled

        try:
            new_state = await self.arun(state, config)
        except NotImplementedError:
            new_state = await database_sync_to_async(self.run, thread_sensitive=False)(state, config)

        if new_state is not None and (messages := getattr(new_state, "messages", [])):
            for message in messages:
                self.dispatcher.message(message)
        return new_state

    def run(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        """DEPRECATED. Use `arun` instead."""
        raise NotImplementedError

    async def arun(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        raise NotImplementedError

    @property
    def context_manager(self) -> AssistantContextManager:
        if self._context_manager is None:
            if self._config is None:
                # Only allow default config in test environments
                if settings.TEST:
                    config = RunnableConfig(configurable={})
                else:
                    raise ValueError("Config is required to create AssistantContextManager")
            else:
                config = self._config
            self._context_manager = AssistantContextManager(self._team, self._user, config)
        return self._context_manager

    @property
    def dispatcher(self) -> AssistantDispatcher:
        """Create a dispatcher for this node"""
        if self._dispatcher:
            return self._dispatcher

        # Set writer from LangGraph context
        try:
            writer = get_stream_writer()
        except RuntimeError:
            # Not in streaming context (e.g., testing)
            # Use noop writer
            def noop(*_args, **_kwargs):
                pass

            writer = noop

        self._dispatcher = AssistantDispatcher(
            writer, node_name=self.node_name, parent_tool_call_id=self._parent_tool_call_id
        )
        return self._dispatcher

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

    def _is_first_turn(self, state: AssistantState) -> bool:
        last_message = state.messages[-1]
        if isinstance(last_message, HumanMessage):
            return last_message == find_start_message(state.messages, start_id=state.start_id)
        return False


AssistantNode = BaseAssistantNode[AssistantState, PartialAssistantState]
