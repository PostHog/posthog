from langchain_core.runnables.base import RunnableLike
from langgraph.graph.state import StateGraph

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.sql_assistant.nodes import SQLAssistantNode
from ee.hogai.sql.nodes import (
    SQLGeneratorNode,
    SQLGeneratorToolsNode,
    SQLPlannerNode,
    SQLPlannerToolsNode,
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

    def add_sql_assistant(
        self,
        next_node: AssistantNodeName = AssistantNodeName.SQL_PLANNER,
    ):
        builder = self._graph
        self._has_start_node = True

        builder.add_edge(AssistantNodeName.START, AssistantNodeName.SQL_ASSISTANT)
        sql_assistant_node = SQLAssistantNode(self._team)
        builder.add_node(AssistantNodeName.SQL_ASSISTANT, sql_assistant_node)
        builder.add_conditional_edges(
            AssistantNodeName.SQL_ASSISTANT,
            sql_assistant_node.router,
            path_map={"next": next_node},
        )
        return self

    def add_sql_planner(
        self,
        next_node: AssistantNodeName = AssistantNodeName.SQL_GENERATOR,
    ):
        builder = self._graph

        sql_planner = SQLPlannerNode(self._team)
        builder.add_node(AssistantNodeName.SQL_PLANNER, sql_planner)
        builder.add_edge(AssistantNodeName.SQL_PLANNER, AssistantNodeName.SQL_PLANNER_TOOLS)

        sql_planner_tools = SQLPlannerToolsNode(self._team)
        builder.add_node(AssistantNodeName.SQL_PLANNER_TOOLS, sql_planner_tools)
        builder.add_conditional_edges(
            AssistantNodeName.SQL_PLANNER_TOOLS,
            sql_planner_tools.router,
            path_map={
                "continue": AssistantNodeName.SQL_PLANNER,
                "plan_found": next_node,
            },
        )

        return self

    def add_sql_generator(self, next_node: AssistantNodeName = AssistantNodeName.END):
        builder = self._graph

        sql_generator = SQLGeneratorNode(self._team)
        builder.add_node(AssistantNodeName.SQL_GENERATOR, sql_generator)

        sql_generator_tools = SQLGeneratorToolsNode(self._team)
        builder.add_node(AssistantNodeName.SQL_GENERATOR_TOOLS, sql_generator_tools)

        builder.add_edge(AssistantNodeName.SQL_GENERATOR_TOOLS, AssistantNodeName.SQL_GENERATOR)
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
        return self.add_sql_assistant().add_sql_planner().add_sql_generator().compile()
