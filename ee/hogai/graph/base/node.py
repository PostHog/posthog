from abc import ABC
from typing import Generic
from uuid import UUID

from django.conf import settings

from langchain_core.runnables import RunnableConfig

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.context import AssistantContextManager
from ee.hogai.graph.base.context import get_node_path, set_node_path
from ee.hogai.graph.mixins import AssistantContextMixin, AssistantDispatcherMixin
from ee.hogai.utils.exceptions import GenerationCanceled
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


class BaseExecutableAssistantNode(
    Generic[StateType, PartialStateType], AssistantContextMixin, AssistantDispatcherMixin, ABC
):
    """Core assistant node with execution logic only."""

    _config: RunnableConfig | None = None
    _context_manager: AssistantContextManager | None = None
    _node_path: tuple[NodePath, ...]

    def __init__(self, team: Team, user: User, node_path: tuple[NodePath, ...]):
        self._team = team
        self._user = user
        self._node_path = node_path

    async def __call__(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        """
        Run the assistant node.
        """
        # Reset the context manager on a new run
        self._context_manager = None
        self._dispatcher = None
        self._config = config

        return await self._execute(state, config)

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
    def node_name(self) -> str:
        config_name: str | None = None
        if self._config and (metadata := self._config.get("metadata")):
            config_name = metadata.get("langgraph_node")
            if config_name is not None:
                config_name = str(config_name)
        return config_name or self.__class__.__name__

    @property
    def node_path(self) -> tuple[NodePath, ...]:
        return (*self._node_path, NodePath(name=self.node_name))

    async def _execute(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        try:
            return await self._arun_with_context(state, config)
        except NotImplementedError:
            pass
        return await database_sync_to_async(self._run_with_context, thread_sensitive=False)(state, config)

    def _run_with_context(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        with set_node_path(self.node_path):
            return self.run(state, config)

    async def _arun_with_context(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        with set_node_path(self.node_path):
            return await self.arun(state, config)


class BaseAssistantNode(BaseExecutableAssistantNode[StateType, PartialStateType]):
    """Assistant node with dispatching and conversation cancellation support."""

    _is_context_path_used: bool = False
    """Whether the constructor set the node path or the context path is used"""

    def __init__(self, team: Team, user: User, node_path: tuple[NodePath, ...] | None = None):
        if node_path is None:
            node_path = get_node_path() or ()
            self._is_context_path_used = True
        super().__init__(team, user, node_path)

    async def __call__(self, state: StateType, config: RunnableConfig) -> PartialStateType | None:
        """
        Run the assistant node and handle cancelled conversation before the node is run.
        """
        # Reset the dispatcher on a new run
        self._context_manager = None
        self._dispatcher = None
        self._config = config

        self.dispatcher.dispatch(NodeStartAction())

        thread_id = (config.get("configurable") or {}).get("thread_id")
        if thread_id and await self._is_conversation_cancelled(thread_id):
            raise GenerationCanceled

        new_state = await self._execute(state, config)

        self.dispatcher.dispatch(NodeEndAction(state=new_state))

        return new_state

    @property
    def node_path(self) -> tuple[NodePath, ...]:
        # If the path is manually set, use it.
        if not self._is_context_path_used:
            return self._node_path
        # Otherwise, construct the path from the context.
        return (*self._node_path, NodePath(name=self.node_name))

    async def _is_conversation_cancelled(self, conversation_id: UUID) -> bool:
        conversation = await self._aget_conversation(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")
        return conversation.status == Conversation.Status.CANCELING


AssistantNode = BaseAssistantNode[AssistantState, PartialAssistantState]
