from langchain_core.runnables import RunnableConfig

from ee.hogai.chat_agent.mode_manager import ChatAgentModeManager
from ee.hogai.core.node import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class AgentLoopGraphNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = ChatAgentModeManager(
            team=self._team,
            user=self._user,
            node_path=self.node_path,
            context_manager=self.context_manager,
            mode=state.agent_mode,
        )
        new_state = await manager.node(state, config)
        return new_state

    def router(self, state: AssistantState):
        manager = ChatAgentModeManager(
            team=self._team,
            user=self._user,
            node_path=self.node_path,
            context_manager=self.context_manager,
            mode=state.agent_mode,
        )
        next_node = manager.node.router(state)
        return next_node


class AgentLoopGraphToolsNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = ChatAgentModeManager(
            team=self._team,
            user=self._user,
            node_path=self.node_path,
            context_manager=self.context_manager,
            mode=state.agent_mode,
        )
        new_state = await manager.tools_node(state, config)
        return new_state

    def router(self, state: AssistantState):
        manager = ChatAgentModeManager(
            team=self._team,
            user=self._user,
            node_path=self.node_path,
            context_manager=self.context_manager,
            mode=state.agent_mode,
        )
        next_node = manager.tools_node.router(state)
        return next_node
