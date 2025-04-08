from langchain_core.runnables.base import RunnableLike
from langgraph.graph.state import StateGraph

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.sql.nodes import (
    SQLGeneratorNode,
    SQLGeneratorToolsNode,
)
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.models.team.team import Team

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

    def compile(self):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        return self._graph.compile(checkpointer=checkpointer)

    def add_sql_generator(self, next_node: AssistantNodeName = AssistantNodeName.END):
        builder = self._graph

        sql_generator = SQLGeneratorNode(self._team)
        builder.add_edge(AssistantNodeName.START, AssistantNodeName.SQL_GENERATOR)
        builder.add_node(AssistantNodeName.SQL_GENERATOR, sql_generator)

        sql_generator_tools = SQLGeneratorToolsNode(self._team)
        builder.add_node(AssistantNodeName.SQL_GENERATOR_TOOLS, sql_generator_tools)

        builder.add_conditional_edges(
            AssistantNodeName.SQL_GENERATOR,
            sql_generator.router,
            path_map={
                "tools": AssistantNodeName.SQL_GENERATOR_TOOLS,
                "next": next_node,
            },
        )

        return self

    def compile_full_graph(self):
        return self.add_sql_generator().compile()
