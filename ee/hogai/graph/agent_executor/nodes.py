from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode

from ee.hogai.graph.agent_modes.mode_manager import AgentModeManager
from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class AgentGraphNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = AgentModeManager(
            team=self._team, user=self._user, node_path=self.node_path, mode=AgentMode.PRODUCT_ANALYTICS
        )
        new_state = await manager.node(state, config)
        return new_state

    def router(self, state: AssistantState):
        manager = AgentModeManager(
            team=self._team, user=self._user, node_path=self.node_path, mode=AgentMode.PRODUCT_ANALYTICS
        )
        next_node = manager.node.router(state)
        return next_node


class AgentGraphToolsNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = AgentModeManager(
            team=self._team, user=self._user, node_path=self.node_path, mode=AgentMode.PRODUCT_ANALYTICS
        )
        new_state = await manager.tools_node(state, config)
        return new_state

    def router(self, state: AssistantState):
        manager = AgentModeManager(
            team=self._team, user=self._user, node_path=self.node_path, mode=AgentMode.PRODUCT_ANALYTICS
        )
        next_node = manager.tools_node.router(state)
        return next_node
