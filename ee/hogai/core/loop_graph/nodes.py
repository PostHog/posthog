from enum import StrEnum

from langchain_core.runnables import RunnableConfig

from posthog.models import Team, User

from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.node import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import NodePath


class AgentLoopNodeType(StrEnum):
    ROOT = "root"
    TOOLS = "tools"


class AgentLoopGraphNode(AssistantNode):
    def __init__(
        self,
        team: Team,
        user: User,
        mode_manager_class: type[AgentModeManager],
        node_type: AgentLoopNodeType,
        node_path: tuple[NodePath, ...] | None = None,
    ):
        self._mode_manager_class = mode_manager_class
        self._node_type = node_type
        super().__init__(team, user, node_path)

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = self._mode_manager_class(
            team=self._team,
            user=self._user,
            node_path=self.node_path,
            context_manager=self.context_manager,
            state=state,
        )
        node = manager.node if self._node_type == AgentLoopNodeType.ROOT else manager.tools_node
        return await node(state, config)

    def router(self, state: AssistantState):
        # BUG: LangGraph calls this router when resuming an interruption, but there is no available config
        # This crashes the context manager because it doesn't have a config
        self._config = RunnableConfig(configurable={})
        manager = self._mode_manager_class(
            team=self._team,
            user=self._user,
            node_path=self.node_path,
            context_manager=self.context_manager,
            state=state,
        )
        node = manager.node if self._node_type == AgentLoopNodeType.ROOT else manager.tools_node
        next_node = node.router(state)
        return next_node
