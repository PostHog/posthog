from collections.abc import Callable

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.agent_executor import AgentExecutorGraph
from ee.hogai.graph.base import BaseAssistantGraph
from ee.hogai.graph.title_generator.nodes import TitleGeneratorNode
from ee.hogai.utils.types.base import AssistantGraphName, AssistantNodeName, AssistantState, PartialAssistantState

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


class AssistantGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.ASSISTANT

    @property
    def state_type(self) -> type[AssistantState]:
        return AssistantState

    def add_title_generator(self, end_node: AssistantNodeName = AssistantNodeName.END):
        self._has_start_node = True

        title_generator = TitleGeneratorNode(self._team, self._user)
        self.add_node(AssistantNodeName.TITLE_GENERATOR, title_generator)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.TITLE_GENERATOR)
        self._graph.add_edge(AssistantNodeName.TITLE_GENERATOR, end_node)
        return self

    def add_root(
        self,
        router: Callable[[AssistantState], AssistantNodeName],
        tools_router: Callable[[AssistantState], AssistantNodeName],
    ):
        agent_executor = AgentExecutorGraph(self._team, self._user).compile_full_graph(
            agent_node_router=router, agent_tools_node_router=tools_router
        )
        self.add_node(AssistantNodeName.ROOT, agent_executor)
        self.add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
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

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        return (
            self.add_title_generator()
            .add_memory_onboarding()
            .add_memory_collector()
            .add_memory_collector_tools()
            .add_root()
            .compile(checkpointer=checkpointer)
        )
