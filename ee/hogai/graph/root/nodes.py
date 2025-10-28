from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.agent.manager import AgentModeManager
from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.composed import MaxNodeName


class RootNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        node = manager.node(state.agent_mode)
        return await node.arun(state, config)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT

    def router(self, state: AssistantState) -> AssistantNodeName:
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        return manager.node(state.agent_mode).router(state)


class RootNodeTools(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT_TOOLS

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        node = manager.tools_node(state.agent_mode)
        return await node.arun(state, config)
