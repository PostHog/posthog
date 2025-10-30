from collections.abc import Callable
from typing import cast

from posthog.models.team.team import Team
from posthog.models.user import User

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.base import BaseAssistantGraph
from ee.hogai.graph.title_generator.nodes import TitleGeneratorNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState

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


class AssistantGraph(BaseAssistantGraph[AssistantState]):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user, AssistantState)

    def add_title_generator(self, end_node: AssistantNodeName = AssistantNodeName.END):
        self._has_start_node = True

        title_generator = TitleGeneratorNode(self._team, self._user)
        self.add_node(AssistantNodeName.TITLE_GENERATOR, title_generator)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.TITLE_GENERATOR)
        self._graph.add_edge(AssistantNodeName.TITLE_GENERATOR, end_node)
        return self

    def add_root(self, router: Callable[[AssistantState], AssistantNodeName] | None = None):
        root_node = RootNode(self._team, self._user)
        self.add_node(AssistantNodeName.ROOT, root_node)
        root_node_tools = RootNodeTools(self._team, self._user)
        self.add_node(AssistantNodeName.ROOT_TOOLS, root_node_tools)
        self._graph.add_conditional_edges(
            AssistantNodeName.ROOT, router or cast(Callable[[AssistantState], AssistantNodeName], root_node.router)
        )
        self._graph.add_edge(AssistantNodeName.ROOT_TOOLS, AssistantNodeName.ROOT)
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
