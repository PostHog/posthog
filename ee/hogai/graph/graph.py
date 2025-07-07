from collections.abc import Hashable
from typing import Optional, cast

from langchain_core.runnables.base import RunnableLike
from langgraph.graph.state import StateGraph

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.title_generator.nodes import TitleGeneratorNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.models.team.team import Team
from posthog.models.user import User

from .funnels.nodes import (
    FunnelGeneratorNode,
    FunnelGeneratorToolsNode,
    FunnelPlannerNode,
    FunnelPlannerToolsNode,
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
    RetentionPlannerNode,
    RetentionPlannerToolsNode,
)
from .root.nodes import RootNode, RootNodeTools
from .sql.nodes import (
    SQLGeneratorNode,
    SQLGeneratorToolsNode,
    SQLPlannerNode,
    SQLPlannerToolsNode,
)
from .trends.nodes import (
    TrendsGeneratorNode,
    TrendsGeneratorToolsNode,
    TrendsPlannerNode,
    TrendsPlannerToolsNode,
)

global_checkpointer = DjangoCheckpointer()


class BaseAssistantGraph:
    _team: Team
    _user: User
    _graph: StateGraph

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user
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

    def compile(self, checkpointer: DjangoCheckpointer | None = None):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        return self._graph.compile(checkpointer=checkpointer or global_checkpointer)


class InsightsAssistantGraph(BaseAssistantGraph):
    def add_rag_context(self):
        builder = self._graph
        self._has_start_node = True
        retriever = InsightRagContextNode(self._team, self._user)
        builder.add_node(AssistantNodeName.INSIGHT_RAG_CONTEXT, retriever)
        builder.add_edge(AssistantNodeName.START, AssistantNodeName.INSIGHT_RAG_CONTEXT)
        builder.add_conditional_edges(
            AssistantNodeName.INSIGHT_RAG_CONTEXT,
            retriever.router,
            path_map={
                "trends": AssistantNodeName.TRENDS_PLANNER,
                "funnel": AssistantNodeName.FUNNEL_PLANNER,
                "retention": AssistantNodeName.RETENTION_PLANNER,
                "sql": AssistantNodeName.SQL_PLANNER,
                "end": AssistantNodeName.END,
            },
        )
        return self

    def add_trends_planner(
        self,
        next_node: AssistantNodeName = AssistantNodeName.TRENDS_GENERATOR,
        end_node: AssistantNodeName = AssistantNodeName.END,
    ):
        builder = self._graph

        create_trends_plan_node = TrendsPlannerNode(self._team, self._user)
        builder.add_node(AssistantNodeName.TRENDS_PLANNER, create_trends_plan_node)
        builder.add_edge(AssistantNodeName.TRENDS_PLANNER, AssistantNodeName.TRENDS_PLANNER_TOOLS)

        create_trends_plan_tools_node = TrendsPlannerToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.TRENDS_PLANNER_TOOLS, create_trends_plan_tools_node)
        builder.add_conditional_edges(
            AssistantNodeName.TRENDS_PLANNER_TOOLS,
            create_trends_plan_tools_node.router,
            path_map={
                "continue": AssistantNodeName.TRENDS_PLANNER,
                "plan_found": next_node,
                "end": end_node,
            },
        )

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

    def add_funnel_planner(
        self,
        next_node: AssistantNodeName = AssistantNodeName.FUNNEL_GENERATOR,
        end_node: AssistantNodeName = AssistantNodeName.END,
    ):
        builder = self._graph

        funnel_planner = FunnelPlannerNode(self._team, self._user)
        builder.add_node(AssistantNodeName.FUNNEL_PLANNER, funnel_planner)
        builder.add_edge(AssistantNodeName.FUNNEL_PLANNER, AssistantNodeName.FUNNEL_PLANNER_TOOLS)

        funnel_planner_tools = FunnelPlannerToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.FUNNEL_PLANNER_TOOLS, funnel_planner_tools)
        builder.add_conditional_edges(
            AssistantNodeName.FUNNEL_PLANNER_TOOLS,
            funnel_planner_tools.router,
            path_map={
                "continue": AssistantNodeName.FUNNEL_PLANNER,
                "plan_found": next_node,
                "end": end_node,
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

    def add_retention_planner(
        self,
        next_node: AssistantNodeName = AssistantNodeName.RETENTION_GENERATOR,
        end_node: AssistantNodeName = AssistantNodeName.END,
    ):
        builder = self._graph

        retention_planner = RetentionPlannerNode(self._team, self._user)
        builder.add_node(AssistantNodeName.RETENTION_PLANNER, retention_planner)
        builder.add_edge(AssistantNodeName.RETENTION_PLANNER, AssistantNodeName.RETENTION_PLANNER_TOOLS)

        retention_planner_tools = RetentionPlannerToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.RETENTION_PLANNER_TOOLS, retention_planner_tools)
        builder.add_conditional_edges(
            AssistantNodeName.RETENTION_PLANNER_TOOLS,
            retention_planner_tools.router,
            path_map={
                "continue": AssistantNodeName.RETENTION_PLANNER,
                "plan_found": next_node,
                "end": end_node,
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

    def add_sql_planner(
        self,
        next_node: AssistantNodeName = AssistantNodeName.SQL_GENERATOR,
        end_node: AssistantNodeName = AssistantNodeName.END,
    ):
        builder = self._graph

        sql_planner = SQLPlannerNode(self._team, self._user)
        builder.add_node(AssistantNodeName.SQL_PLANNER, sql_planner)
        builder.add_edge(AssistantNodeName.SQL_PLANNER, AssistantNodeName.SQL_PLANNER_TOOLS)

        sql_planner_tools = SQLPlannerToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.SQL_PLANNER_TOOLS, sql_planner_tools)
        builder.add_conditional_edges(
            AssistantNodeName.SQL_PLANNER_TOOLS,
            sql_planner_tools.router,
            path_map={
                "continue": AssistantNodeName.SQL_PLANNER,
                "plan_found": next_node,
                "end": end_node,
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
            .add_trends_planner()
            .add_trends_generator(next_node=next_node)
            .add_funnel_planner()
            .add_funnel_generator(next_node=next_node)
            .add_retention_planner()
            .add_retention_generator(next_node=next_node)
            .add_sql_planner()
            .add_sql_generator(next_node=next_node)
        )

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        return self.add_query_creation_flow().add_query_executor().compile(checkpointer=checkpointer)


class AssistantGraph(BaseAssistantGraph):
    def add_root(
        self,
        path_map: Optional[dict[Hashable, AssistantNodeName]] = None,
    ):
        builder = self._graph
        path_map = path_map or {
            "insights": AssistantNodeName.INSIGHTS_SUBGRAPH,
            "search_documentation": AssistantNodeName.INKEEP_DOCS,
            "root": AssistantNodeName.ROOT,
            "memory_onboarding": AssistantNodeName.MEMORY_ONBOARDING,
            "end": AssistantNodeName.END,
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
        builder = self._graph
        insights_assistant_graph = InsightsAssistantGraph(self._team, self._user)
        compiled_graph = insights_assistant_graph.compile_full_graph()
        builder.add_node(AssistantNodeName.INSIGHTS_SUBGRAPH, compiled_graph)
        builder.add_edge(AssistantNodeName.INSIGHTS_SUBGRAPH, next_node)
        return self

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

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        return (
            self.add_title_generator()
            .add_memory_onboarding()
            .add_memory_collector()
            .add_memory_collector_tools()
            .add_root()
            .add_insights()
            .add_inkeep_docs()
            .compile(checkpointer=checkpointer)
        )
