from uuid import UUID

from langchain_core.runnables import RunnableConfig

from posthog.models import Team, User

from ee.hogai.core.context import get_node_path
from ee.hogai.core.executable import BaseAgentExecutable
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


class BaseAssistantNode(BaseAgentExecutable[StateType, PartialStateType]):
    """Assistant node with dispatching and conversation cancellation support."""

    _is_context_path_used: bool = False
    """Whether the constructor set the node path or the node path from the context is used"""

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
