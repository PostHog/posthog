from collections.abc import Callable, Coroutine, Hashable
from typing import Any, Generic, Literal, Optional, Protocol, cast, runtime_checkable

from langgraph.graph.state import CompiledStateGraph, StateGraph

from posthog.schema import ReasoningMessage

from posthog.models.team.team import Team
from posthog.models.user import User

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.session_summaries.nodes import SessionSummarizationNode
from ee.hogai.graph.title_generator.nodes import TitleGeneratorNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, StateType
from ee.hogai.utils.types.base import BaseState
from ee.hogai.utils.types.composed import MaxNodeName

from .dashboards.nodes import DashboardCreationNode
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
from .root.nodes import RootNode, RootNodeTools

global_checkpointer = DjangoCheckpointer()


# Type alias for async reasoning message function, takes a state and an optional default message content and returns an optional reasoning message
GetReasoningMessageAfunc = Callable[[BaseState, str | None], Coroutine[Any, Any, ReasoningMessage | None]]
GetReasoningMessageMapType = dict[MaxNodeName, GetReasoningMessageAfunc]


# Protocol to check if a node has a reasoning message function at runtime
@runtime_checkable
class HasReasoningMessage(Protocol):
    get_reasoning_message: GetReasoningMessageAfunc


class AssistantCompiledStateGraph(CompiledStateGraph):
    """Wrapper around CompiledStateGraph that preserves reasoning message information.

    Note: This uses __dict__ copying as a workaround since CompiledStateGraph
    doesn't support standard inheritance. This is brittle and may break with
    library updates.
    """

    def __init__(
        self, compiled_graph: CompiledStateGraph, aget_reasoning_message_by_node_name: GetReasoningMessageMapType
    ):
        # Copy the internal state from the compiled graph without calling super().__init__
        # This is a workaround since CompiledStateGraph doesn't support standard inheritance
        self.__dict__.update(compiled_graph.__dict__)
        self.aget_reasoning_message_by_node_name = aget_reasoning_message_by_node_name


class BaseAssistantGraph(Generic[StateType]):
    _team: Team
    _user: User
    _graph: StateGraph
    aget_reasoning_message_by_node_name: GetReasoningMessageMapType

    def __init__(self, team: Team, user: User, state_type: type[StateType]):
        self._team = team
        self._user = user
        self._graph = StateGraph(state_type)
        self._has_start_node = False
        self.aget_reasoning_message_by_node_name = {}

    def add_edge(self, from_node: MaxNodeName, to_node: MaxNodeName):
        if from_node == AssistantNodeName.START:
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: MaxNodeName, action: Any):
        self._graph.add_node(node, action)
        if isinstance(action, HasReasoningMessage):
            self.aget_reasoning_message_by_node_name[node] = action.get_reasoning_message
        return self

    def add_subgraph(self, node_name: MaxNodeName, subgraph: AssistantCompiledStateGraph):
        self._graph.add_node(node_name, subgraph)
        self.aget_reasoning_message_by_node_name.update(subgraph.aget_reasoning_message_by_node_name)
        return self

    def compile(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        # TRICKY: We check `is not None` because False has a special meaning of "no checkpointer", which we want to pass on
        compiled_graph = self._graph.compile(
            checkpointer=checkpointer if checkpointer is not None else global_checkpointer
        )
        return AssistantCompiledStateGraph(
            compiled_graph, aget_reasoning_message_by_node_name=self.aget_reasoning_message_by_node_name
        )

    def add_title_generator(self, end_node: MaxNodeName = AssistantNodeName.END):
        self._has_start_node = True

        title_generator = TitleGeneratorNode(self._team, self._user)
        self._graph.add_node(AssistantNodeName.TITLE_GENERATOR, title_generator)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.TITLE_GENERATOR)
        self._graph.add_edge(AssistantNodeName.TITLE_GENERATOR, end_node)
        return self


class AssistantGraph(BaseAssistantGraph[AssistantState]):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user, AssistantState)

    def add_root(
        self,
        path_map: Optional[dict[Hashable, AssistantNodeName]] = None,
    ):
        path_map = path_map or {
            "insights": AssistantNodeName.INSIGHTS_SUBGRAPH,
            "search_documentation": AssistantNodeName.INKEEP_DOCS,
            "root": AssistantNodeName.ROOT,
            "end": AssistantNodeName.END,
            "insights_search": AssistantNodeName.INSIGHTS_SEARCH,
            "session_summarization": AssistantNodeName.SESSION_SUMMARIZATION,
            "create_dashboard": AssistantNodeName.DASHBOARD_CREATION,
        }
        root_node = RootNode(self._team, self._user)
        self.add_node(AssistantNodeName.ROOT, root_node)
        root_node_tools = RootNodeTools(self._team, self._user)
        self.add_node(AssistantNodeName.ROOT_TOOLS, root_node_tools)
        self._graph.add_edge(AssistantNodeName.ROOT, AssistantNodeName.ROOT_TOOLS)
        self._graph.add_conditional_edges(
            AssistantNodeName.ROOT_TOOLS, root_node_tools.router, path_map=cast(dict[Hashable, str], path_map)
        )
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
            .add_insights_search()
            .add_session_summarization()
            .add_dashboard_creation()
            .compile(checkpointer=checkpointer)
        )
