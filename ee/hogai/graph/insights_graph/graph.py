from typing import Literal, Optional

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.base import BaseAssistantGraph
from ee.hogai.utils.types.base import AssistantGraphName, AssistantNodeName, AssistantState, PartialAssistantState

from ..funnels.nodes import FunnelGeneratorNode, FunnelGeneratorToolsNode
from ..query_executor.nodes import QueryExecutorNode
from ..query_planner.nodes import QueryPlannerNode, QueryPlannerToolsNode
from ..rag.nodes import InsightRagContextNode
from ..retention.nodes import RetentionGeneratorNode, RetentionGeneratorToolsNode
from ..sql.nodes import SQLGeneratorNode, SQLGeneratorToolsNode
from ..trends.nodes import TrendsGeneratorNode, TrendsGeneratorToolsNode


class InsightsGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.INSIGHTS

    @property
    def state_type(self) -> type[AssistantState]:
        return AssistantState

    def add_rag_context(self):
        self._has_start_node = True
        retriever = InsightRagContextNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.INSIGHT_RAG_CONTEXT, retriever)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.INSIGHT_RAG_CONTEXT)
        self._graph.add_edge(AssistantNodeName.INSIGHT_RAG_CONTEXT, AssistantNodeName.QUERY_PLANNER)
        return self

    def add_trends_generator(self, next_node: AssistantNodeName = AssistantNodeName.QUERY_EXECUTOR):
        trends_generator = TrendsGeneratorNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.TRENDS_GENERATOR, trends_generator)

        trends_generator_tools = TrendsGeneratorToolsNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.TRENDS_GENERATOR_TOOLS, trends_generator_tools)

        self._graph.add_edge(AssistantNodeName.TRENDS_GENERATOR_TOOLS, AssistantNodeName.TRENDS_GENERATOR)
        self._graph.add_conditional_edges(
            AssistantNodeName.TRENDS_GENERATOR,
            trends_generator.router,
            path_map={
                "tools": AssistantNodeName.TRENDS_GENERATOR_TOOLS,
                "next": next_node,
            },
        )

        return self

    def add_funnel_generator(self, next_node: AssistantNodeName = AssistantNodeName.QUERY_EXECUTOR):
        funnel_generator = FunnelGeneratorNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.FUNNEL_GENERATOR, funnel_generator)

        funnel_generator_tools = FunnelGeneratorToolsNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.FUNNEL_GENERATOR_TOOLS, funnel_generator_tools)

        self._graph.add_edge(AssistantNodeName.FUNNEL_GENERATOR_TOOLS, AssistantNodeName.FUNNEL_GENERATOR)
        self._graph.add_conditional_edges(
            AssistantNodeName.FUNNEL_GENERATOR,
            funnel_generator.router,
            path_map={
                "tools": AssistantNodeName.FUNNEL_GENERATOR_TOOLS,
                "next": next_node,
            },
        )

        return self

    def add_retention_generator(self, next_node: AssistantNodeName = AssistantNodeName.QUERY_EXECUTOR):
        retention_generator = RetentionGeneratorNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.RETENTION_GENERATOR, retention_generator)

        retention_generator_tools = RetentionGeneratorToolsNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.RETENTION_GENERATOR_TOOLS, retention_generator_tools)

        self._graph.add_edge(AssistantNodeName.RETENTION_GENERATOR_TOOLS, AssistantNodeName.RETENTION_GENERATOR)
        self._graph.add_conditional_edges(
            AssistantNodeName.RETENTION_GENERATOR,
            retention_generator.router,
            path_map={
                "tools": AssistantNodeName.RETENTION_GENERATOR_TOOLS,
                "next": next_node,
            },
        )

        return self

    def add_query_planner(
        self,
        path_map: Optional[
            dict[Literal["trends", "funnel", "retention", "sql", "continue", "end"], AssistantNodeName]
        ] = None,
    ):
        query_planner = QueryPlannerNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.QUERY_PLANNER, query_planner)
        self._graph.add_edge(AssistantNodeName.QUERY_PLANNER, AssistantNodeName.QUERY_PLANNER_TOOLS)

        query_planner_tools = QueryPlannerToolsNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.QUERY_PLANNER_TOOLS, query_planner_tools)
        self._graph.add_conditional_edges(
            AssistantNodeName.QUERY_PLANNER_TOOLS,
            query_planner_tools.router,
            path_map=path_map  # type: ignore
            or {
                "continue": AssistantNodeName.QUERY_PLANNER,
                "trends": AssistantNodeName.TRENDS_GENERATOR,
                "funnel": AssistantNodeName.FUNNEL_GENERATOR,
                "retention": AssistantNodeName.RETENTION_GENERATOR,
                "sql": AssistantNodeName.SQL_GENERATOR,
                "end": AssistantNodeName.END,
            },
        )

        return self

    def add_sql_generator(self, next_node: AssistantNodeName = AssistantNodeName.QUERY_EXECUTOR):
        sql_generator = SQLGeneratorNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.SQL_GENERATOR, sql_generator)

        sql_generator_tools = SQLGeneratorToolsNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.SQL_GENERATOR_TOOLS, sql_generator_tools)

        self._graph.add_edge(AssistantNodeName.SQL_GENERATOR_TOOLS, AssistantNodeName.SQL_GENERATOR)
        self._graph.add_conditional_edges(
            AssistantNodeName.SQL_GENERATOR,
            sql_generator.router,
            path_map={
                "tools": AssistantNodeName.SQL_GENERATOR_TOOLS,
                "next": next_node,
            },
        )

        return self

    def add_query_executor(self, next_node: AssistantNodeName = AssistantNodeName.END):
        query_executor_node = QueryExecutorNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.QUERY_EXECUTOR, query_executor_node)
        self._graph.add_edge(AssistantNodeName.QUERY_EXECUTOR, next_node)
        return self

    def add_query_creation_flow(self, next_node: AssistantNodeName = AssistantNodeName.QUERY_EXECUTOR):
        """Add all nodes and edges EXCEPT query execution."""
        return (
            self.add_rag_context()
            .add_query_planner()
            .add_trends_generator(next_node=next_node)
            .add_funnel_generator(next_node=next_node)
            .add_retention_generator(next_node=next_node)
            .add_sql_generator(next_node=next_node)
        )

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        return self.add_query_creation_flow().add_query_executor().compile(checkpointer=checkpointer)
