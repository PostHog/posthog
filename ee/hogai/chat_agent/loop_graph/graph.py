from collections.abc import Callable
from typing import Literal, cast

from ee.hogai.core.base import BaseAssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types.base import AssistantGraphName, AssistantNodeName, AssistantState, PartialAssistantState

from .nodes import AgentLoopGraphNode, AgentLoopGraphToolsNode


class ChatAgentLoopGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.AGENT_EXECUTOR

    @property
    def state_type(self) -> type[AssistantState]:
        return AssistantState

    def add_agent_node(self, router: Callable[[AssistantState], AssistantNodeName] | None = None):
        self._has_start_node = True
        root_node = AgentLoopGraphNode(self._team, self._user)
        self.add_node(AssistantNodeName.ROOT, root_node)
        self._graph.add_conditional_edges(
            AssistantNodeName.ROOT,
            router or cast(Callable[[AssistantState], AssistantNodeName], root_node.router),
        )
        return self

    def add_agent_tools_node(self, router: Callable[[AssistantState], AssistantNodeName] | None = None):
        agent_tools_node = AgentLoopGraphToolsNode(self._team, self._user)
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
        return self.add_agent_node().add_agent_tools_node().compile(checkpointer=checkpointer)
