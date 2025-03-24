from collections.abc import Hashable
from typing import Optional, cast

from langchain_core.runnables.base import RunnableLike
from langgraph.graph.state import StateGraph

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.memory.nodes import (
    MemoryCollectorNode,
    MemoryCollectorToolsNode,
    MemoryInitializerInterruptNode,
    MemoryInitializerNode,
    MemoryOnboardingNode,
)
from ee.hogai.query_executor.nodes import QueryExecutorNode
from ee.hogai.root.nodes import RootNode, RootNodeTools
from ee.hogai.thinking.nodes import ThinkingNode
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

    def add_root(
        self,
        path_map: Optional[dict[Hashable, AssistantNodeName]] = None,
    ):
        builder = self._graph
        path_map = path_map or {
            "root": AssistantNodeName.ROOT,
            "end": AssistantNodeName.END,
        }
        root_node = RootNode(self._team)
        builder.add_node(AssistantNodeName.ROOT, root_node)
        root_node_tools = RootNodeTools(self._team)
        builder.add_node(AssistantNodeName.ROOT_TOOLS, root_node_tools)
        builder.add_edge(AssistantNodeName.ROOT, AssistantNodeName.ROOT_TOOLS)
        builder.add_conditional_edges(
            AssistantNodeName.ROOT_TOOLS, root_node_tools.router, path_map=cast(dict[Hashable, str], path_map)
        )
        return self

    def add_thinking_node(
        self,
        next_node: AssistantNodeName = AssistantNodeName.SQL_PLANNER,
    ):
        builder = self._graph
        thinking_node = ThinkingNode(self._team)
        builder.add_node(AssistantNodeName.THINKING, thinking_node)
        builder.add_conditional_edges(
            AssistantNodeName.THINKING,
            thinking_node.router,
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

    def add_query_executor(self, next_node: AssistantNodeName = AssistantNodeName.END):
        builder = self._graph
        query_executor_node = QueryExecutorNode(self._team)
        builder.add_node(AssistantNodeName.QUERY_EXECUTOR, query_executor_node)
        builder.add_edge(AssistantNodeName.QUERY_EXECUTOR, next_node)
        return self

    def add_memory_initializer(self, next_node: AssistantNodeName = AssistantNodeName.THINKING):
        builder = self._graph
        self._has_start_node = True

        memory_onboarding = MemoryOnboardingNode(self._team)
        memory_initializer = MemoryInitializerNode(self._team)
        memory_initializer_interrupt = MemoryInitializerInterruptNode(self._team)

        builder.add_node(AssistantNodeName.MEMORY_ONBOARDING, memory_onboarding)
        builder.add_node(AssistantNodeName.MEMORY_INITIALIZER, memory_initializer)
        builder.add_node(AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT, memory_initializer_interrupt)

        builder.add_conditional_edges(
            AssistantNodeName.START,
            memory_onboarding.should_run,
            path_map={True: AssistantNodeName.MEMORY_ONBOARDING, False: next_node},
        )
        builder.add_conditional_edges(
            AssistantNodeName.MEMORY_ONBOARDING,
            memory_onboarding.router,
            path_map={"continue": next_node, "initialize_memory": AssistantNodeName.MEMORY_INITIALIZER},
        )
        builder.add_conditional_edges(
            AssistantNodeName.MEMORY_INITIALIZER,
            memory_initializer.router,
            path_map={"continue": next_node, "interrupt": AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT},
        )
        builder.add_edge(AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT, next_node)

        return self

    def add_memory_collector(
        self,
        next_node: AssistantNodeName = AssistantNodeName.END,
        tools_node: AssistantNodeName = AssistantNodeName.MEMORY_COLLECTOR_TOOLS,
    ):
        builder = self._graph
        self._has_start_node = True

        memory_collector = MemoryCollectorNode(self._team)
        builder.add_edge(AssistantNodeName.START, AssistantNodeName.MEMORY_COLLECTOR)
        builder.add_node(AssistantNodeName.MEMORY_COLLECTOR, memory_collector)
        builder.add_conditional_edges(
            AssistantNodeName.MEMORY_COLLECTOR,
            memory_collector.router,
            path_map={"tools": tools_node, "next": next_node},
        )
        return self

    def add_memory_collector_tools(self):
        builder = self._graph
        memory_collector_tools = MemoryCollectorToolsNode(self._team)
        builder.add_node(AssistantNodeName.MEMORY_COLLECTOR_TOOLS, memory_collector_tools)
        builder.add_edge(AssistantNodeName.MEMORY_COLLECTOR_TOOLS, AssistantNodeName.MEMORY_COLLECTOR)
        return self

    def compile_full_graph(self):
        return (
            self.add_memory_initializer()
            .add_memory_collector()
            .add_memory_collector_tools()
            .add_thinking_node()  # Add thinking node after memory initialization
            .add_sql_planner()
            .add_sql_generator()
            .compile()
        )
