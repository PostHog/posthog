from abc import ABC
from typing import Generic
from uuid import UUID

from django.conf import settings

from langchain_core.runnables import RunnableConfig

from posthog.schema import HumanMessage

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.context import AssistantContextManager
from ee.hogai.graph.mixins import AssistantContextMixin, NodePathMixin
from ee.hogai.utils.dispatcher import AssistantDispatcher, create_dispatcher_from_config
from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.helpers import find_start_message
from ee.hogai.utils.types.base import (
    AssistantState,
    NodeEndAction,
    NodePath,
    NodeStartAction,
    PartialAssistantState,
    PartialStateType,
    StateType,
)
from ee.models import Conversation


class BaseAssistantNode(Generic[StateType, PartialStateType], AssistantContextMixin, NodePathMixin, ABC):
    _config: RunnableConfig | None = None
    _context_manager: AssistantContextManager | None = None
    _dispatcher: AssistantDispatcher | None = None

    def __init__(self, team: Team, user: User, node_path: tuple[NodePath, ...] | None = None):
        self._team = team
        self._user = user
        self._node_path = node_path or ()

    async def __call__(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        """
        Run the assistant node and handle cancelled conversation before the node is run.
        """
        # Reset the context manager and dispatcher on a new run
        self._context_manager = None
        self._dispatcher = None
        self._config = config

        self.dispatcher.dispatch(NodeStartAction())

        thread_id = (config.get("configurable") or {}).get("thread_id")
        if thread_id and await self._is_conversation_cancelled(thread_id):
            raise GenerationCanceled

        try:
            new_state = await self.arun(state, config)
        except NotImplementedError:
            new_state = await database_sync_to_async(self.run, thread_sensitive=False)(state, config)

        self.dispatcher.dispatch(NodeEndAction(state=new_state))

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
        self._dispatcher = create_dispatcher_from_config(self._config or {}, self._node_path)
        return self._dispatcher

    async def _is_conversation_cancelled(self, conversation_id: UUID) -> bool:
        conversation = await self._aget_conversation(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")
        return conversation.status == Conversation.Status.CANCELING

    def _is_first_turn(self, state: AssistantState) -> bool:
        last_message = state.messages[-1]
        if isinstance(last_message, HumanMessage):
            return last_message == find_start_message(state.messages, start_id=state.start_id)
        return False


AssistantNode = BaseAssistantNode[AssistantState, PartialAssistantState]
