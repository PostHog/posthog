from collections.abc import Hashable
from typing import Any, Generic, Literal, Optional, cast

from langgraph.graph.state import StateGraph

from posthog.models.team.team import Team
from posthog.models.user import User

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.billing.nodes import BillingNode
from ee.hogai.graph.query_planner.nodes import QueryPlannerNode, QueryPlannerToolsNode
from ee.hogai.graph.session_summaries.nodes import SessionSummarizationNode
from ee.hogai.graph.title_generator.nodes import TitleGeneratorNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, StateType
from ee.hogai.utils.types.composed import MaxNodeName

from .dashboards.nodes import DashboardCreationNode
from .funnels.nodes import FunnelGeneratorNode, FunnelGeneratorToolsNode
from .inkeep_docs.nodes import InkeepDocsNode
from .insights.nodes import InsightSearchNode
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
from .retention.nodes import RetentionGeneratorNode, RetentionGeneratorToolsNode
from .root.nodes import RootNode, RootNodeTools
from .sql.nodes import SQLGeneratorNode, SQLGeneratorToolsNode
from .trends.nodes import TrendsGeneratorNode, TrendsGeneratorToolsNode

global_checkpointer = DjangoCheckpointer()


class BaseAssistantGraph(Generic[StateType]):
    _team: Team
    _user: User
    _graph: StateGraph
    _parent_tool_call_id: str | None

    def __init__(self, team: Team, user: User, state_type: type[StateType], parent_tool_call_id: str | None = None):
        self._team = team
        self._user = user
        self._graph = StateGraph(state_type)
        self._has_start_node = False
        self._parent_tool_call_id = parent_tool_call_id

    def add_edge(self, from_node: MaxNodeName, to_node: MaxNodeName):
        if from_node == AssistantNodeName.START:
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: MaxNodeName, action: Any):
        if self._parent_tool_call_id:
            action._parent_tool_call_id = self._parent_tool_call_id
        self._graph.add_node(node, action)
        return self

    def compile(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        # TRICKY: We check `is not None` because False has a special meaning of "no checkpointer", which we want to pass on
        compiled_graph = self._graph.compile(
            checkpointer=checkpointer if checkpointer is not None else global_checkpointer
        )
        return compiled_graph

    def add_title_generator(self, end_node: MaxNodeName = AssistantNodeName.END):
        self._has_start_node = True

        title_generator = TitleGeneratorNode(self._team, self._user)
        self.add_node(AssistantNodeName.TITLE_GENERATOR, title_generator)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.TITLE_GENERATOR)
        self._graph.add_edge(AssistantNodeName.TITLE_GENERATOR, end_node)
        return self


class InsightsAssistantGraph(BaseAssistantGraph[AssistantState]):
    def __init__(self, team: Team, user: User, tool_call_id: str | None = None):
        super().__init__(team, user, AssistantState, tool_call_id)

    def add_rag_context(self):
        self._has_start_node = True
        retriever = InsightRagContextNode(self._team, self._user)
        self.add_node(AssistantNodeName.INSIGHT_RAG_CONTEXT, retriever)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.INSIGHT_RAG_CONTEXT)
        self._graph.add_edge(AssistantNodeName.INSIGHT_RAG_CONTEXT, AssistantNodeName.QUERY_PLANNER)
        return self

    def add_trends_generator(self, next_node: AssistantNodeName = AssistantNodeName.QUERY_EXECUTOR):
        trends_generator = TrendsGeneratorNode(self._team, self._user)
        self.add_node(AssistantNodeName.TRENDS_GENERATOR, trends_generator)

        trends_generator_tools = TrendsGeneratorToolsNode(self._team, self._user)
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
        funnel_generator = FunnelGeneratorNode(self._team, self._user)
        self.add_node(AssistantNodeName.FUNNEL_GENERATOR, funnel_generator)

        funnel_generator_tools = FunnelGeneratorToolsNode(self._team, self._user)
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
        retention_generator = RetentionGeneratorNode(self._team, self._user)
        self.add_node(AssistantNodeName.RETENTION_GENERATOR, retention_generator)

        retention_generator_tools = RetentionGeneratorToolsNode(self._team, self._user)
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
        query_planner = QueryPlannerNode(self._team, self._user)
        self.add_node(AssistantNodeName.QUERY_PLANNER, query_planner)
        self._graph.add_edge(AssistantNodeName.QUERY_PLANNER, AssistantNodeName.QUERY_PLANNER_TOOLS)

        query_planner_tools = QueryPlannerToolsNode(self._team, self._user)
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
        sql_generator = SQLGeneratorNode(self._team, self._user)
        self.add_node(AssistantNodeName.SQL_GENERATOR, sql_generator)

        sql_generator_tools = SQLGeneratorToolsNode(self._team, self._user)
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
        query_executor_node = QueryExecutorNode(self._team, self._user)
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


class AssistantGraph(BaseAssistantGraph[AssistantState]):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user, AssistantState)

    def add_root(
        self,
        path_map: Optional[dict[Hashable, AssistantNodeName]] = None,
        tools_node: AssistantNodeName = AssistantNodeName.ROOT_TOOLS,
    ):
        path_map = path_map or {
            "insights": AssistantNodeName.INSIGHTS_SUBGRAPH,
            "search_documentation": AssistantNodeName.INKEEP_DOCS,
            "root": AssistantNodeName.ROOT,
            "billing": AssistantNodeName.BILLING,
            "end": AssistantNodeName.END,
            "insights_search": AssistantNodeName.INSIGHTS_SEARCH,
            "session_summarization": AssistantNodeName.SESSION_SUMMARIZATION,
            "create_dashboard": AssistantNodeName.DASHBOARD_CREATION,
        }
        root_node = RootNode(self._team, self._user)
        self.add_node(AssistantNodeName.ROOT, root_node)
        root_node_tools = RootNodeTools(self._team, self._user)
        self.add_node(AssistantNodeName.ROOT_TOOLS, root_node_tools)
        self._graph.add_edge(AssistantNodeName.ROOT, tools_node)
        self._graph.add_conditional_edges(
            AssistantNodeName.ROOT_TOOLS, root_node_tools.router, path_map=cast(dict[Hashable, str], path_map)
        )
        return self

    def add_insights(self, next_node: AssistantNodeName = AssistantNodeName.ROOT):
        insights_assistant_graph = InsightsAssistantGraph(self._team, self._user)
        compiled_graph = insights_assistant_graph.compile_full_graph()
        self.add_node(AssistantNodeName.INSIGHTS_SUBGRAPH, compiled_graph)
        self._graph.add_edge(AssistantNodeName.INSIGHTS_SUBGRAPH, next_node)
        return self

    def add_memory_onboarding(
        self,
        next_node: AssistantNodeName = AssistantNodeName.ROOT,
    ):
        self._has_start_node = True

        memory_onboarding = MemoryOnboardingNode(self._team, self._user)
        memory_initializer = MemoryInitializerNode(self._team, self._user)
        memory_initializer_interrupt = MemoryInitializerInterruptNode(self._team, self._user)
        memory_onboarding_enquiry = MemoryOnboardingEnquiryNode(self._team, self._user)
        memory_onboarding_enquiry_interrupt = MemoryOnboardingEnquiryInterruptNode(self._team, self._user)
        memory_onboarding_finalize = MemoryOnboardingFinalizeNode(self._team, self._user)

        self.add_node(AssistantNodeName.MEMORY_ONBOARDING, memory_onboarding)
        self.add_node(AssistantNodeName.MEMORY_INITIALIZER, memory_initializer)
        self.add_node(AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT, memory_initializer_interrupt)
        self.add_node(AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY, memory_onboarding_enquiry)
        self.add_node(AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY_INTERRUPT, memory_onboarding_enquiry_interrupt)
        self.add_node(AssistantNodeName.MEMORY_ONBOARDING_FINALIZE, memory_onboarding_finalize)

        self._graph.add_conditional_edges(
            AssistantNodeName.START,
            memory_onboarding.should_run_onboarding_at_start,
            {
                "memory_onboarding": AssistantNodeName.MEMORY_ONBOARDING,
                "continue": next_node,
            },
        )
        self._graph.add_edge(AssistantNodeName.MEMORY_ONBOARDING, AssistantNodeName.MEMORY_INITIALIZER)
        self._graph.add_conditional_edges(
            AssistantNodeName.MEMORY_INITIALIZER,
            memory_initializer.router,
            path_map={
                "continue": AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
                "interrupt": AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT,
            },
        )
        self._graph.add_edge(
            AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT, AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY
        )
        self._graph.add_conditional_edges(
            AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
            memory_onboarding_enquiry.router,
            path_map={
                "continue": AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
                "interrupt": AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY_INTERRUPT,
            },
        )
        self._graph.add_edge(
            AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY_INTERRUPT, AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY
        )
        self._graph.add_edge(AssistantNodeName.MEMORY_ONBOARDING_FINALIZE, next_node)
        return self

    def add_memory_collector(
        self,
        next_node: AssistantNodeName = AssistantNodeName.END,
        tools_node: AssistantNodeName = AssistantNodeName.MEMORY_COLLECTOR_TOOLS,
    ):
        self._has_start_node = True

        memory_collector = MemoryCollectorNode(self._team, self._user)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.MEMORY_COLLECTOR)
        self.add_node(AssistantNodeName.MEMORY_COLLECTOR, memory_collector)
        self._graph.add_conditional_edges(
            AssistantNodeName.MEMORY_COLLECTOR,
            memory_collector.router,
            path_map={"tools": tools_node, "next": next_node},
        )
        return self

    def add_memory_collector_tools(self):
        memory_collector_tools = MemoryCollectorToolsNode(self._team, self._user)
        self.add_node(AssistantNodeName.MEMORY_COLLECTOR_TOOLS, memory_collector_tools)
        self._graph.add_edge(AssistantNodeName.MEMORY_COLLECTOR_TOOLS, AssistantNodeName.MEMORY_COLLECTOR)
        return self

    def add_inkeep_docs(self, path_map: Optional[dict[Hashable, AssistantNodeName]] = None):
        """Add the Inkeep docs search node to the graph."""
        path_map = path_map or {
            "end": AssistantNodeName.END,
            "root": AssistantNodeName.ROOT,
        }
        inkeep_docs_node = InkeepDocsNode(self._team, self._user)
        self.add_node(AssistantNodeName.INKEEP_DOCS, inkeep_docs_node)
        self._graph.add_conditional_edges(
            AssistantNodeName.INKEEP_DOCS,
            inkeep_docs_node.router,
            path_map=cast(dict[Hashable, str], path_map),
        )
        return self

    def add_billing(self):
        billing_node = BillingNode(self._team, self._user)
        self.add_node(AssistantNodeName.BILLING, billing_node)
        self._graph.add_edge(AssistantNodeName.BILLING, AssistantNodeName.ROOT)
        return self

    def add_insights_search(self, end_node: AssistantNodeName = AssistantNodeName.END):
        path_map = {
            "end": end_node,
            "root": AssistantNodeName.ROOT,
        }

        insights_search_node = InsightSearchNode(self._team, self._user)
        self.add_node(AssistantNodeName.INSIGHTS_SEARCH, insights_search_node)
        self._graph.add_conditional_edges(
            AssistantNodeName.INSIGHTS_SEARCH,
            insights_search_node.router,
            path_map=cast(dict[Hashable, str], path_map),
        )
        return self

    def add_session_summarization(self, end_node: AssistantNodeName = AssistantNodeName.END):
        session_summarization_node = SessionSummarizationNode(self._team, self._user)
        self.add_node(AssistantNodeName.SESSION_SUMMARIZATION, session_summarization_node)
        self._graph.add_edge(AssistantNodeName.SESSION_SUMMARIZATION, AssistantNodeName.ROOT)
        return self

    def add_dashboard_creation(self, end_node: AssistantNodeName = AssistantNodeName.END):
        builder = self._graph
        dashboard_creation_node = DashboardCreationNode(self._team, self._user)
        builder.add_node(AssistantNodeName.DASHBOARD_CREATION, dashboard_creation_node)
        builder.add_edge(AssistantNodeName.DASHBOARD_CREATION, AssistantNodeName.ROOT)
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
            .add_session_summarization()
            .add_dashboard_creation()
            .compile(checkpointer=checkpointer)
        )
