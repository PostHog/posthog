from collections.abc import Hashable
from typing import Any, Generic, Literal, Optional, cast

from langchain_core.messages import AIMessageChunk
from langchain_core.runnables.base import RunnableLike
from langgraph.graph.state import StateGraph
from pydantic import BaseModel

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.schema_generator.nodes import SchemaGeneratorNode
from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL
from ee.hogai.utils.helpers import find_last_ui_context, should_output_assistant_message
from ee.hogai.utils.state import (
    GraphMessageUpdateTuple,
    GraphTaskStartedUpdateTuple,
    GraphValueUpdateTuple,
    validate_value_update,
)
from ee.hogai.utils.types import (
    AssistantMode,
    AssistantNodeName,
    AssistantState,
    PartialAssistantState,
)
from posthog.models import Action, Team, User
from posthog.schema import (
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    ReasoningMessage,
)

from .base import AssistantNode, StateType
from .filter_options.types import FilterOptionsNodeName
from .funnels.nodes import (
    FunnelGeneratorNode,
    FunnelGeneratorToolsNode,
)
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
from .query_planner.nodes import QueryPlannerNode, QueryPlannerToolsNode
from .rag.nodes import InsightRagContextNode
from .retention.nodes import (
    RetentionGeneratorNode,
    RetentionGeneratorToolsNode,
)
from .root.nodes import RootNode, RootNodeTools
from .sql.nodes import SQLGeneratorNode, SQLGeneratorToolsNode
from .title_generator.nodes import TitleGeneratorNode
from .trends.nodes import TrendsGeneratorNode, TrendsGeneratorToolsNode

global_checkpointer = DjangoCheckpointer()


class BaseAssistantGraph(Generic[StateType]):
    _team: Team
    _user: User
    _graph: StateGraph

    def __init__(self, team: Team, user: User, state_type: type[StateType]):
        self._team = team
        self._user = user
        self._graph = StateGraph(state_type)
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


class InsightsAssistantGraph(BaseAssistantGraph[AssistantState]):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user, AssistantState)

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


VISUALIZATION_NODES: dict[AssistantNodeName, type[SchemaGeneratorNode]] = {
    AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
    AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
    AssistantNodeName.RETENTION_GENERATOR: RetentionGeneratorNode,
    AssistantNodeName.SQL_GENERATOR: SQLGeneratorNode,
}

VISUALIZATION_NODES_TOOL_CALL_MODE: dict[AssistantNodeName, type[AssistantNode]] = {
    **VISUALIZATION_NODES,
    AssistantNodeName.QUERY_EXECUTOR: QueryExecutorNode,
}

STREAMING_NODES: set[AssistantNodeName | FilterOptionsNodeName] = {
    AssistantNodeName.ROOT,
    AssistantNodeName.INKEEP_DOCS,
    AssistantNodeName.MEMORY_ONBOARDING,
    AssistantNodeName.MEMORY_INITIALIZER,
    AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
    AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
    FilterOptionsNodeName.FILTER_OPTIONS,
}
"""Nodes that can stream messages to the client."""


VERBOSE_NODES: set[AssistantNodeName | FilterOptionsNodeName] = STREAMING_NODES | {
    AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT,
    AssistantNodeName.ROOT_TOOLS,
    FilterOptionsNodeName.FILTER_OPTIONS_TOOLS,
}
"""Nodes that can send messages to the client."""

THINKING_NODES: set[AssistantNodeName | FilterOptionsNodeName] = {
    AssistantNodeName.QUERY_PLANNER,
    FilterOptionsNodeName.FILTER_OPTIONS,
}
"""Nodes that pass on thinking messages to the client. Current implementation assumes o3/o4 style of reasoning summaries!"""


class AssistantGraph(BaseAssistantGraph[AssistantState]):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user, AssistantState)

    def add_root(
        self,
        path_map: Optional[dict[Hashable, AssistantNodeName]] = None,
    ):
        builder = self._graph
        path_map = path_map or {
            "insights": AssistantNodeName.INSIGHTS_SUBGRAPH,
            "search_documentation": AssistantNodeName.INKEEP_DOCS,
            "root": AssistantNodeName.ROOT,
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
            .add_insights_search()
            .compile(checkpointer=checkpointer)
        )

    def process_value_update(self, update: GraphValueUpdateTuple) -> list[BaseModel] | None:
        _, maybe_state_update = update
        state_update = validate_value_update(maybe_state_update)
        # this needs full type annotation otherwise mypy complains
        visualization_nodes: (
            dict[AssistantNodeName, type[AssistantNode]] | dict[AssistantNodeName, type[SchemaGeneratorNode]]
        ) = VISUALIZATION_NODES if self._mode == AssistantMode.ASSISTANT else VISUALIZATION_NODES_TOOL_CALL_MODE
        if intersected_nodes := state_update.keys() & visualization_nodes.keys():
            # Reset chunks when schema validation fails.
            self._chunks = AIMessageChunk(content="")

            node_name: AssistantNodeName | FilterOptionsNodeName = intersected_nodes.pop()
            node_val = state_update[node_name]
            if not isinstance(node_val, PartialAssistantState):
                return None
            if node_val.messages:
                return list(node_val.messages)
            elif node_val.intermediate_steps:
                return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)]

        for node_name in VERBOSE_NODES:
            if node_val := state_update.get(node_name):
                if isinstance(node_val, PartialAssistantState) and node_val.messages:
                    self._chunks = AIMessageChunk(content="")
                    _messages: list[BaseModel] = []
                    for candidate_message in node_val.messages:
                        if should_output_assistant_message(candidate_message):
                            _messages.append(candidate_message)
                    return _messages

        for node_name in THINKING_NODES:
            if node_val := state_update.get(node_name):
                # If update involves new state from a thinking node, we reset the thinking headline to be sure
                self._reasoning_headline_chunk = None

        return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)]

    def process_message_update(self, update: GraphMessageUpdateTuple) -> BaseModel | None:
        langchain_message, langgraph_state = update[1]
        if isinstance(langchain_message, AIMessageChunk):
            node_name: AssistantNodeName | FilterOptionsNodeName = langgraph_state["langgraph_node"]
            if node_name in STREAMING_NODES:
                self._chunks += langchain_message  # type: ignore
                if node_name == AssistantNodeName.MEMORY_INITIALIZER:
                    if not MemoryInitializerNode.should_process_message_chunk(langchain_message):
                        return None
                    else:
                        return AssistantMessage(
                            content=MemoryInitializerNode.format_message(cast(str, self._chunks.content))
                        )
                if self._chunks.content:
                    # Only return an in-progress message if there is already some content (and not e.g. just tool calls)
                    return AssistantMessage(content=cast(str, self._chunks.content))
            if reasoning := langchain_message.additional_kwargs.get("reasoning"):
                if reasoning_headline := self._chunk_reasoning_headline(reasoning):
                    return ReasoningMessage(content=reasoning_headline)
        return None

    async def process_task_started_update(self, update: GraphTaskStartedUpdateTuple) -> BaseModel | None:
        _, task_update = update
        node_name = task_update["payload"]["name"]  # type: ignore
        node_input = task_update["payload"]["input"]  # type: ignore
        if reasoning_message := await self._node_to_reasoning_message(node_name, node_input):
            return reasoning_message
        return None

    def _chunk_reasoning_headline(self, reasoning: dict[str, Any]) -> Optional[str]:
        """Process a chunk of OpenAI `reasoning`, and if a new headline was just finalized, return it."""
        try:
            summary_text_chunk = reasoning["summary"][0]["text"]
        except (KeyError, IndexError):
            self._reasoning_headline_chunk = None  # Not expected, so let's just reset
            return None

        index_of_bold_in_text = summary_text_chunk.find("**")
        if index_of_bold_in_text != -1:
            # The headline is either beginning or ending with bold text in this chunk
            if self._reasoning_headline_chunk is None:
                # If we don't have a headline, we should start reading it
                remaining_text = summary_text_chunk[index_of_bold_in_text + 2 :]  # Remove the ** from start
                # Check if there's another ** in the remaining text (complete headline in one chunk)
                end_index = remaining_text.find("**")
                if end_index != -1:
                    # Complete headline in one chunk
                    self._last_reasoning_headline = remaining_text[:end_index]
                    return self._last_reasoning_headline
                else:
                    # Start of headline, continue chunking
                    self._reasoning_headline_chunk = remaining_text
            else:
                # If we already have a headline, it means we should wrap up
                self._reasoning_headline_chunk += summary_text_chunk[:index_of_bold_in_text]  # Remove the ** from end
                self._last_reasoning_headline = self._reasoning_headline_chunk
                self._reasoning_headline_chunk = None
                return self._last_reasoning_headline
        elif self._reasoning_headline_chunk is not None:
            # No bold text in this chunk, so we should just add the text to the headline
            self._reasoning_headline_chunk += summary_text_chunk

        return None

    async def _node_to_reasoning_message(
        self, node_name: AssistantNodeName | FilterOptionsNodeName, input: AssistantState
    ) -> Optional[ReasoningMessage]:
        match node_name:
            case AssistantNodeName.QUERY_PLANNER | FilterOptionsNodeName.FILTER_OPTIONS:
                substeps: list[str] = []
                if input:
                    if intermediate_steps := input.intermediate_steps:
                        for action, _ in intermediate_steps:
                            assert isinstance(action.tool_input, dict)
                            match action.tool:
                                case "retrieve_event_properties":
                                    substeps.append(f"Exploring `{action.tool_input['event_name']}` event's properties")
                                case "retrieve_entity_properties":
                                    substeps.append(f"Exploring {action.tool_input['entity']} properties")
                                case "retrieve_event_property_values":
                                    substeps.append(
                                        f"Analyzing `{action.tool_input['event_name']}` event's property `{action.tool_input['property_name']}`"
                                    )
                                case "retrieve_entity_property_values":
                                    substeps.append(
                                        f"Analyzing {action.tool_input['entity']} property `{action.tool_input['property_name']}`"
                                    )
                                case "retrieve_action_properties" | "retrieve_action_property_values":
                                    try:
                                        action_model = await Action.objects.aget(
                                            pk=action.tool_input["action_id"], team__project_id=self._team.project_id
                                        )
                                        if action.tool == "retrieve_action_properties":
                                            substeps.append(f"Exploring `{action_model.name}` action properties")
                                        elif action.tool == "retrieve_action_property_values":
                                            substeps.append(
                                                f"Analyzing `{action.tool_input['property_name']}` action property of `{action_model.name}`"
                                            )
                                    except Action.DoesNotExist:
                                        pass

                # We don't want to reset back to just "Picking relevant events" after running QueryPlannerTools,
                # so we reuse the last reasoning headline when going back to QueryPlanner
                return ReasoningMessage(
                    content=self._last_reasoning_headline or "Picking relevant events and properties", substeps=substeps
                )
            case AssistantNodeName.TRENDS_GENERATOR:
                return ReasoningMessage(content="Creating trends query")
            case AssistantNodeName.FUNNEL_GENERATOR:
                return ReasoningMessage(content="Creating funnel query")
            case AssistantNodeName.RETENTION_GENERATOR:
                return ReasoningMessage(content="Creating retention query")
            case AssistantNodeName.SQL_GENERATOR:
                return ReasoningMessage(content="Creating SQL query")
            case AssistantNodeName.ROOT_TOOLS:
                assert isinstance(input.messages[-1], AssistantMessage)
                tool_calls = input.messages[-1].tool_calls or []
                assert len(tool_calls) <= 1
                if len(tool_calls) == 0:
                    return None
                tool_call = tool_calls[0]
                if tool_call.name == "create_and_query_insight":
                    return ReasoningMessage(content="Coming up with an insight")
                if tool_call.name == "search_documentation":
                    return ReasoningMessage(content="Checking PostHog docs")
                # This tool should be in CONTEXTUAL_TOOL_NAME_TO_TOOL, but it might not be in the rare case
                # when the tool has been removed from the backend since the user's frontent was loaded
                ToolClass = CONTEXTUAL_TOOL_NAME_TO_TOOL.get(tool_call.name)  # type: ignore
                return ReasoningMessage(
                    content=ToolClass(team=self._team, user=self._user).thinking_message
                    if ToolClass
                    else f"Running tool {tool_call.name}"
                )
            case AssistantNodeName.ROOT:
                ui_context = find_last_ui_context(input.messages)
                if ui_context and (ui_context.dashboards or ui_context.insights):
                    return ReasoningMessage(content="Calculating context")
                return None
            case _:
                return None
