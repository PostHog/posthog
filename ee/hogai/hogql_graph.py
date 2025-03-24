from collections.abc import Hashable
from typing import Optional, cast

from langchain_core.runnables.base import RunnableLike
from langgraph.graph.state import StateGraph

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.models.team.team import Team
from ee.hogai.hogql.nodes import HogQLNode

checkpointer = DjangoCheckpointer()


class HogQLGraph:
    _team: Team
    _graph: StateGraph

    def __init__(self, team: Team):
        self._team = team
        self._graph = StateGraph(AssistantState)
        self._has_start_node = False

    def add_edge(self, from_node: AssistantNodeName, to_node: AssistantNodeName):
        if from_node == AssistantNodeName.START:
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: AssistantNodeName, action: RunnableLike):
        self._graph.add_node(node, action)
        return self
    
    def add_hogql(
        self,
        path_map: Optional[dict[Hashable, AssistantNodeName]] = None,
    ):
        builder = self._graph
        path_map = path_map or {
            "end": AssistantNodeName.END,
        }
        hogql_node = HogQLNode(self._team)
        builder.add_node(AssistantNodeName.HOGQL, hogql_node)

        return self

    def compile(self):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        return self._graph.compile(checkpointer=checkpointer)

    def compile_simple_graph(self):
        """
        Compiles a simple graph that just goes from START to END.
        """
        return (
            self.add_edge(AssistantNodeName.START, AssistantNodeName.HOGQL)
            .add_hogql()
            .compile()
        )
