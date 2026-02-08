from collections.abc import Callable
from typing import Literal

from ee.hogai.chat_agent.memory.nodes import (
    MemoryCollectorNode,
    MemoryCollectorToolsNode,
    MemoryInitializerInterruptNode,
    MemoryInitializerNode,
    MemoryOnboardingEnquiryInterruptNode,
    MemoryOnboardingEnquiryNode,
    MemoryOnboardingFinalizeNode,
    MemoryOnboardingNode,
)
from ee.hogai.chat_agent.mode_manager import ChatAgentModeManager
from ee.hogai.chat_agent.slash_commands.nodes import SlashCommandHandlerNode
from ee.hogai.core.loop_graph.graph import AgentLoopGraph
from ee.hogai.core.title_generator.nodes import TitleGeneratorNode
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types.base import AssistantGraphName, AssistantNodeName, AssistantState


class AssistantGraph(AgentLoopGraph):
    @property
    def mode_manager_class(self) -> type[ChatAgentModeManager]:
        return ChatAgentModeManager

    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.ASSISTANT

    def add_title_generator(self, end_node: AssistantNodeName = AssistantNodeName.END):
        self._has_start_node = True

        title_generator = TitleGeneratorNode(self._team, self._user)
        self.add_node(AssistantNodeName.TITLE_GENERATOR, title_generator)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.TITLE_GENERATOR)
        self._graph.add_edge(AssistantNodeName.TITLE_GENERATOR, end_node)
        return self

    def add_root(
        self,
        router: Callable[[AssistantState], AssistantNodeName] | None = None,
        tools_router: Callable[[AssistantState], AssistantNodeName] | None = None,
    ):
        # Merge the agent graph into the main graph.
        # Subgraphs incorrectly merge messages, so please don't use them here.
        return self.add_agent_node(router=router).add_agent_tools_node(router=tools_router)

    def add_memory_onboarding(
        self,
        next_node: AssistantNodeName = AssistantNodeName.ROOT,
    ):
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
            memory_onboarding_enquiry.arouter,
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
        memory_collector = MemoryCollectorNode(self._team, self._user)
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

    def add_slash_command_handler(self):
        """
        The SlashCommandHandlerNode detects slash commands and executes them directly.
        Non-command messages are routed to the normal conversation flow.
        """
        self._has_start_node = True

        slash_command_handler = SlashCommandHandlerNode(self._team, self._user)
        self.add_node(AssistantNodeName.SLASH_COMMAND_HANDLER, slash_command_handler)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.SLASH_COMMAND_HANDLER)
        self._graph.add_conditional_edges(
            AssistantNodeName.SLASH_COMMAND_HANDLER,
            slash_command_handler.arouter,
        )

        return self

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        return (
            self.add_title_generator()
            .add_slash_command_handler()
            .add_memory_onboarding()
            .add_memory_collector()
            .add_memory_collector_tools()
            .add_root()
            .compile(checkpointer=checkpointer)
        )
