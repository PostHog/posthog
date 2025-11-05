from typing import Literal

from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.agent.mode_manager import AgentModeManager
from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.composed import MaxNodeName

SLASH_COMMAND_INIT = "/init"
SLASH_COMMAND_REMEMBER = "/remember"


class RootNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        return await manager.node(state, config)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT

    def router(self, state: AssistantState) -> AssistantNodeName:
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        return manager.node.router(state)


class RootNodeTools(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT_TOOLS

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        return await manager.tools_node(state, config)

    def router(self, state: AssistantState) -> Literal["root", "end"]:
        manager = AgentModeManager(self._team, self._user, state.agent_mode)
        return manager.tools_node.router(state)
