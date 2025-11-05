from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.agent_modes.mode_manager import AgentModeManager
from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class AgentRootNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        return await manager.node(state, config)

    def router(self, state: AssistantState):
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        return manager.node.router(state)


class AgentRootToolsNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        return await manager.tools_node(state, config)

    def router(self, state: AssistantState):
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        return manager.tools_node.router(state)
