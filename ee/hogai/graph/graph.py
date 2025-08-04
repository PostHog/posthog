from collections.abc import Hashable
from typing import Literal, Optional, cast, Generic

from langchain_core.runnables.base import RunnableLike
from langgraph.graph.state import StateGraph

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.query_planner.nodes import QueryPlannerNode, QueryPlannerToolsNode
from ee.hogai.graph.billing.nodes import BillingNode
from ee.hogai.graph.title_generator.nodes import TitleGeneratorNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, GraphType, GraphContext

from posthog.models.team.team import Team
from posthog.models.user import User

from .funnels.nodes import (
    FunnelGeneratorNode,
    FunnelGeneratorToolsNode,
)
from .inkeep_docs.nodes import InkeepDocsNode
from .memory.nodes import (
    MemoryCollectorNode,
    MemoryCollectorToolsNode,
    MemoryInitializerInterruptNode,
    MemoryInitializerNode,
    MemoryOnboardingEnquiryInterruptNode,
    MemoryOnboardingEnquiryNode,
    MemoryOnboardingFinalizeNode,
    MemoryOnboardingNode,
)
from .query_executor.nodes import QueryExecutorNode
from .rag.nodes import InsightRagContextNode
from .retention.nodes import (
    RetentionGeneratorNode,
    RetentionGeneratorToolsNode,
)
from .root.nodes import RootNode, RootNodeTools
from .sql.nodes import SQLGeneratorNode, SQLGeneratorToolsNode
from .trends.nodes import TrendsGeneratorNode, TrendsGeneratorToolsNode
from .base import StateType
from .insights.nodes import InsightSearchNode


class BaseAssistantGraph(Generic[StateType]):
    _team: Team
    _user: User
    _graph: StateGraph
    _graph_type: GraphType
    _context: GraphContext

    def __init__(
        self, team: Team, user: User, state_type: type[StateType], graph_type: GraphType, context: GraphContext
    ):
        self._team = team
        self._user = user
        self._graph = StateGraph(state_type)
        self._graph_type = graph_type
        self._context = context
        self._has_start_node = False

    def add_edge(self, from_node: AssistantNodeName, to_node: AssistantNodeName):
        if from_node == AssistantNodeName.START:
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: AssistantNodeName, action: RunnableLike):
        self._graph.add_node(node, action)
        return self

    def compile(
        self,
        checkpointer: DjangoCheckpointer | None = None,
    ):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")

        if checkpointer is None:
            checkpointer = DjangoCheckpointer(self._graph_type, self._context)

        return self._graph.compile(checkpointer=checkpointer)

    def add_subgraph(
        self,
        node_name: AssistantNodeName,
        subgraph_class,
        graph_type: GraphType,
        next_node: AssistantNodeName | None = None,
    ):
        """
        Add a subgraph with automatic context management.

        This helper automatically configures the subgraph with SUBGRAPH context
        and handles checkpointer setup.
        """
        # Create subgraph with subgraph-specific checkpointer
        subgraph_instance = subgraph_class(self._team, self._user)
        subgraph_checkpointer = DjangoCheckpointer(graph_type, GraphContext.SUBGRAPH)

        compiled_subgraph = subgraph_instance.compile(checkpointer=subgraph_checkpointer)

        self._graph.add_node(node_name, compiled_subgraph)

        if next_node:
            self._graph.add_edge(node_name, next_node)

        return self


class InsightsAssistantGraph(BaseAssistantGraph[AssistantState]):
    def __init__(self, team: Team, user: User, context: GraphContext = GraphContext.ROOT):
        super().__init__(team, user, AssistantState, GraphType.INSIGHTS, context)

    def add_rag_context(self):
        builder = self._graph
        self._has_start_node = True
        retriever = InsightRagContextNode(self._team, self._user)
        builder.add_node(AssistantNodeName.INSIGHT_RAG_CONTEXT, retriever)
        builder.add_edge(AssistantNodeName.START, AssistantNodeName.INSIGHT_RAG_CONTEXT)
        builder.add_edge(AssistantNodeName.INSIGHT_RAG_CONTEXT, AssistantNodeName.QUERY_PLANNER)
        return self

    def add_trends_generator(self, next_node: AssistantNodeName = AssistantNodeName.QUERY_EXECUTOR):
        builder = self._graph

        trends_generator = TrendsGeneratorNode(self._team, self._user)
        builder.add_node(AssistantNodeName.TRENDS_GENERATOR, trends_generator)

        trends_generator_tools = TrendsGeneratorToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.TRENDS_GENERATOR_TOOLS, trends_generator_tools)

        builder.add_edge(AssistantNodeName.TRENDS_GENERATOR_TOOLS, AssistantNodeName.TRENDS_GENERATOR)
        builder.add_conditional_edges(
            AssistantNodeName.TRENDS_GENERATOR,
            trends_generator.router,
            path_map={
                "tools": AssistantNodeName.TRENDS_GENERATOR_TOOLS,
                "next": next_node,
            },
        )

        return self

    def add_funnel_generator(self, next_node: AssistantNodeName = AssistantNodeName.QUERY_EXECUTOR):
        builder = self._graph

        funnel_generator = FunnelGeneratorNode(self._team, self._user)
        builder.add_node(AssistantNodeName.FUNNEL_GENERATOR, funnel_generator)

        funnel_generator_tools = FunnelGeneratorToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.FUNNEL_GENERATOR_TOOLS, funnel_generator_tools)

        builder.add_edge(AssistantNodeName.FUNNEL_GENERATOR_TOOLS, AssistantNodeName.FUNNEL_GENERATOR)
        builder.add_conditional_edges(
            AssistantNodeName.FUNNEL_GENERATOR,
            funnel_generator.router,
            path_map={
                "tools": AssistantNodeName.FUNNEL_GENERATOR_TOOLS,
                "next": next_node,
            },
        )

        return self

    def add_retention_generator(self, next_node: AssistantNodeName = AssistantNodeName.QUERY_EXECUTOR):
        builder = self._graph

        retention_generator = RetentionGeneratorNode(self._team, self._user)
        builder.add_node(AssistantNodeName.RETENTION_GENERATOR, retention_generator)

        retention_generator_tools = RetentionGeneratorToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.RETENTION_GENERATOR_TOOLS, retention_generator_tools)

        builder.add_edge(AssistantNodeName.RETENTION_GENERATOR_TOOLS, AssistantNodeName.RETENTION_GENERATOR)
        builder.add_conditional_edges(
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
        builder = self._graph

        query_planner = QueryPlannerNode(self._team, self._user)
        builder.add_node(AssistantNodeName.QUERY_PLANNER, query_planner)
        builder.add_edge(AssistantNodeName.QUERY_PLANNER, AssistantNodeName.QUERY_PLANNER_TOOLS)

        query_planner_tools = QueryPlannerToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.QUERY_PLANNER_TOOLS, query_planner_tools)
        builder.add_conditional_edges(
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
        builder = self._graph

        sql_generator = SQLGeneratorNode(self._team, self._user)
        builder.add_node(AssistantNodeName.SQL_GENERATOR, sql_generator)

        sql_generator_tools = SQLGeneratorToolsNode(self._team, self._user)
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
        query_executor_node = QueryExecutorNode(self._team, self._user)
        builder.add_node(AssistantNodeName.QUERY_EXECUTOR, query_executor_node)
        builder.add_edge(AssistantNodeName.QUERY_EXECUTOR, next_node)
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


class AssistantGraph(BaseAssistantGraph[AssistantState]):
    def __init__(self, team: Team, user: User, context: GraphContext = GraphContext.ROOT):
        super().__init__(team, user, AssistantState, GraphType.ASSISTANT, context)

    def add_root(
        self,
        path_map: Optional[dict[Hashable, AssistantNodeName]] = None,
    ):
        builder = self._graph
        path_map = path_map or {
            "insights": AssistantNodeName.INSIGHTS_SUBGRAPH,
            "search_documentation": AssistantNodeName.INKEEP_DOCS,
            "root": AssistantNodeName.ROOT,
            "billing": AssistantNodeName.BILLING,
            "end": AssistantNodeName.END,
            "insights_search": AssistantNodeName.INSIGHTS_SEARCH,
        }
        root_node = RootNode(self._team, self._user)
        builder.add_node(AssistantNodeName.ROOT, root_node)
        root_node_tools = RootNodeTools(self._team, self._user)
        builder.add_node(AssistantNodeName.ROOT_TOOLS, root_node_tools)
        builder.add_edge(AssistantNodeName.ROOT, AssistantNodeName.ROOT_TOOLS)
        builder.add_conditional_edges(
            AssistantNodeName.ROOT_TOOLS, root_node_tools.router, path_map=cast(dict[Hashable, str], path_map)
        )
        return self

    def add_insights(self, next_node: AssistantNodeName = AssistantNodeName.ROOT):
        return self.add_subgraph(
            AssistantNodeName.INSIGHTS_SUBGRAPH, InsightsAssistantGraph, GraphType.INSIGHTS, next_node
        )

    def add_memory_onboarding(
        self,
        next_node: AssistantNodeName = AssistantNodeName.ROOT,
        insights_next_node: AssistantNodeName = AssistantNodeName.INSIGHTS_SUBGRAPH,
    ):
        builder = self._graph
        self._has_start_node = True

        memory_onboarding = MemoryOnboardingNode(self._team, self._user)
        memory_initializer = MemoryInitializerNode(self._team, self._user)
        memory_initializer_interrupt = MemoryInitializerInterruptNode(self._team, self._user)
        memory_onboarding_enquiry = MemoryOnboardingEnquiryNode(self._team, self._user)
        memory_onboarding_enquiry_interrupt = MemoryOnboardingEnquiryInterruptNode(self._team, self._user)
        memory_onboarding_finalize = MemoryOnboardingFinalizeNode(self._team, self._user)

        builder.add_node(AssistantNodeName.MEMORY_ONBOARDING, memory_onboarding)
        builder.add_node(AssistantNodeName.MEMORY_INITIALIZER, memory_initializer)
        builder.add_node(AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT, memory_initializer_interrupt)
        builder.add_node(AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY, memory_onboarding_enquiry)
        builder.add_node(AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY_INTERRUPT, memory_onboarding_enquiry_interrupt)
        builder.add_node(AssistantNodeName.MEMORY_ONBOARDING_FINALIZE, memory_onboarding_finalize)

        builder.add_conditional_edges(
            AssistantNodeName.START,
            memory_onboarding.should_run_onboarding_at_start,
            {
                "memory_onboarding": AssistantNodeName.MEMORY_ONBOARDING,
                "continue": next_node,
            },
        )

        builder.add_conditional_edges(
            AssistantNodeName.MEMORY_ONBOARDING,
            memory_onboarding.router,
            path_map={
                "initialize_memory": AssistantNodeName.MEMORY_INITIALIZER,
                "onboarding_enquiry": AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
            },
        )
        builder.add_conditional_edges(
            AssistantNodeName.MEMORY_INITIALIZER,
            memory_initializer.router,
            path_map={
                "continue": AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
                "interrupt": AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT,
            },
        )
        builder.add_edge(AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT, AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY)
        builder.add_conditional_edges(
            AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
            memory_onboarding_enquiry.router,
            path_map={
                "continue": AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
                "interrupt": AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY_INTERRUPT,
            },
        )
        builder.add_edge(
            AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY_INTERRUPT, AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY
        )
        builder.add_conditional_edges(
            AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
            memory_onboarding_finalize.router,
            path_map={"continue": next_node, "insights": insights_next_node},
        )
        return self

    def add_memory_collector(
        self,
        next_node: AssistantNodeName = AssistantNodeName.END,
        tools_node: AssistantNodeName = AssistantNodeName.MEMORY_COLLECTOR_TOOLS,
    ):
        builder = self._graph
        self._has_start_node = True

        memory_collector = MemoryCollectorNode(self._team, self._user)
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
        memory_collector_tools = MemoryCollectorToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.MEMORY_COLLECTOR_TOOLS, memory_collector_tools)
        builder.add_edge(AssistantNodeName.MEMORY_COLLECTOR_TOOLS, AssistantNodeName.MEMORY_COLLECTOR)
        return self

    def add_inkeep_docs(self, path_map: Optional[dict[Hashable, AssistantNodeName]] = None):
        """Add the Inkeep docs search node to the graph."""
        builder = self._graph
        path_map = path_map or {
            "end": AssistantNodeName.END,
            "root": AssistantNodeName.ROOT,
        }
        inkeep_docs_node = InkeepDocsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.INKEEP_DOCS, inkeep_docs_node)
        builder.add_conditional_edges(
            AssistantNodeName.INKEEP_DOCS,
            inkeep_docs_node.router,
            path_map=cast(dict[Hashable, str], path_map),
        )
        return self

    def add_title_generator(self, end_node: AssistantNodeName = AssistantNodeName.END):
        builder = self._graph
        self._has_start_node = True

        title_generator = TitleGeneratorNode(self._team, self._user)
        builder.add_node(AssistantNodeName.TITLE_GENERATOR, title_generator)
        builder.add_edge(AssistantNodeName.START, AssistantNodeName.TITLE_GENERATOR)
        builder.add_edge(AssistantNodeName.TITLE_GENERATOR, end_node)
        return self

    def add_billing(self):
        builder = self._graph
        billing_node = BillingNode(self._team, self._user)
        builder.add_node(AssistantNodeName.BILLING, billing_node)
        builder.add_edge(AssistantNodeName.BILLING, AssistantNodeName.ROOT)
        return self

    def add_insights_search(self, end_node: AssistantNodeName = AssistantNodeName.END):
        builder = self._graph
        path_map = {
            "end": end_node,
            "root": AssistantNodeName.ROOT,
        }

        insights_search_node = InsightSearchNode(self._team, self._user)
        builder.add_node(AssistantNodeName.INSIGHTS_SEARCH, insights_search_node)
        builder.add_conditional_edges(
            AssistantNodeName.INSIGHTS_SEARCH,
            insights_search_node.router,
            path_map=cast(dict[Hashable, str], path_map),
        )
        return self

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        return (
            self.add_title_generator()
            .add_memory_onboarding()
            .add_memory_collector()
            .add_memory_collector_tools()
            .add_root()
            .add_insights()
            .add_inkeep_docs()
            .add_billing()
            .add_insights_search()
            .compile(checkpointer=checkpointer)
        )
