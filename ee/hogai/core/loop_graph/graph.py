from abc import abstractmethod
from collections.abc import Callable
from typing import Literal, cast

from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.base import BaseAssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types.base import AssistantGraphName, AssistantNodeName, AssistantState, PartialAssistantState

from .nodes import AgentLoopGraphNode, AgentLoopNodeType


class AgentLoopGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
    @property
    @abstractmethod
    def mode_manager_class(self) -> type[AgentModeManager]: ...

    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.AGENT_EXECUTOR

    @property
    def state_type(self) -> type[AssistantState]:
        return AssistantState

    def add_agent_node(
        self, router: Callable[[AssistantState], AssistantNodeName] | None = None, is_start_node: bool = False
    ):
        root_node = AgentLoopGraphNode(self._team, self._user, self.mode_manager_class, AgentLoopNodeType.ROOT)
        self.add_node(AssistantNodeName.ROOT, root_node)
        if is_start_node:
            self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            self._has_start_node = True
        self._graph.add_conditional_edges(
            AssistantNodeName.ROOT,
            router or cast(Callable[[AssistantState], AssistantNodeName], root_node.router),
        )
        return self

    def add_agent_tools_node(self, router: Callable[[AssistantState], AssistantNodeName] | None = None):
        agent_tools_node = AgentLoopGraphNode(self._team, self._user, self.mode_manager_class, AgentLoopNodeType.TOOLS)
        self.add_node(AssistantNodeName.ROOT_TOOLS, agent_tools_node)
        self._graph.add_conditional_edges(
            AssistantNodeName.ROOT_TOOLS,
            router or cast(Callable[[AssistantState], AssistantNodeName], agent_tools_node.router),
            path_map={
                "root": AssistantNodeName.ROOT,
                "end": AssistantNodeName.END,
            },
        )
        return self

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        return self.add_agent_node(is_start_node=True).add_agent_tools_node().compile(checkpointer=checkpointer)
