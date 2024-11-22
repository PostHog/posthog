from collections.abc import Generator, Hashable, Iterator
from typing import Any, Literal, Optional, TypedDict, TypeGuard, Union, cast

from langchain_core.messages import AIMessageChunk
from langfuse.callback import CallbackHandler
from langgraph.graph.state import CompiledStateGraph, StateGraph
from pydantic import BaseModel
from sentry_sdk import capture_exception

from ee import settings
from ee.hogai.funnels.nodes import (
    FunnelGeneratorNode,
    FunnelGeneratorToolsNode,
    FunnelPlannerNode,
    FunnelPlannerToolsNode,
)
from ee.hogai.router.nodes import RouterNode
from ee.hogai.schema_generator.nodes import SchemaGeneratorNode
from ee.hogai.summarizer.nodes import SummarizerNode
from ee.hogai.trends.nodes import (
    TrendsGeneratorNode,
    TrendsGeneratorToolsNode,
    TrendsPlannerNode,
    TrendsPlannerToolsNode,
)
from ee.hogai.utils import AssistantNodeName, AssistantState, Conversation
from posthog.models.team.team import Team
from posthog.schema import (
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    FailureMessage,
    VisualizationMessage,
)

if settings.LANGFUSE_PUBLIC_KEY:
    langfuse_handler = CallbackHandler(
        public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY, host=settings.LANGFUSE_HOST
    )
else:
    langfuse_handler = None


def is_value_update(update: list[Any]) -> TypeGuard[tuple[Literal["values"], dict[AssistantNodeName, AssistantState]]]:
    """
    Transition between nodes.
    """
    return len(update) == 2 and update[0] == "updates"


class LangGraphState(TypedDict):
    langgraph_node: AssistantNodeName


def is_message_update(
    update: list[Any],
) -> TypeGuard[tuple[Literal["messages"], tuple[Union[AIMessageChunk, Any], LangGraphState]]]:
    """
    Streaming of messages. Returns a partial state.
    """
    return len(update) == 2 and update[0] == "messages"


def is_state_update(update: list[Any]) -> TypeGuard[tuple[Literal["updates"], AssistantState]]:
    """
    Update of the state.
    """
    return len(update) == 2 and update[0] == "values"


VISUALIZATION_NODES: dict[AssistantNodeName, type[SchemaGeneratorNode]] = {
    AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
    AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
}


class AssistantGraph:
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

    def compile(self):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        return self._graph.compile()

    def add_start(self):
        return self.add_edge(AssistantNodeName.START, AssistantNodeName.ROUTER)

    def add_router(
        self,
        path_map: Optional[dict[Hashable, AssistantNodeName]] = None,
    ):
        builder = self._graph
        path_map = path_map or {
            "trends": AssistantNodeName.TRENDS_PLANNER,
            "funnel": AssistantNodeName.FUNNEL_PLANNER,
        }
        router_node = RouterNode(self._team)
        builder.add_node(AssistantNodeName.ROUTER, router_node.run)
        builder.add_conditional_edges(
            AssistantNodeName.ROUTER,
            router_node.router,
            path_map=cast(dict[Hashable, str], path_map),
        )
        return self

    def add_trends_planner(self, next_node: AssistantNodeName = AssistantNodeName.TRENDS_GENERATOR):
        builder = self._graph

        create_trends_plan_node = TrendsPlannerNode(self._team)
        builder.add_node(AssistantNodeName.TRENDS_PLANNER, create_trends_plan_node.run)
        builder.add_conditional_edges(
            AssistantNodeName.TRENDS_PLANNER,
            create_trends_plan_node.router,
            path_map={
                "tools": AssistantNodeName.TRENDS_PLANNER_TOOLS,
            },
        )

        create_trends_plan_tools_node = TrendsPlannerToolsNode(self._team)
        builder.add_node(AssistantNodeName.TRENDS_PLANNER_TOOLS, create_trends_plan_tools_node.run)
        builder.add_conditional_edges(
            AssistantNodeName.TRENDS_PLANNER_TOOLS,
            create_trends_plan_tools_node.router,
            path_map={
                "continue": AssistantNodeName.TRENDS_PLANNER,
                "plan_found": next_node,
            },
        )

        return self

    def add_trends_generator(self, next_node: AssistantNodeName = AssistantNodeName.SUMMARIZER):
        builder = self._graph

        trends_generator = TrendsGeneratorNode(self._team)
        builder.add_node(AssistantNodeName.TRENDS_GENERATOR, trends_generator.run)

        trends_generator_tools = TrendsGeneratorToolsNode(self._team)
        builder.add_node(AssistantNodeName.TRENDS_GENERATOR_TOOLS, trends_generator_tools.run)

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

    def add_funnel_planner(self, next_node: AssistantNodeName = AssistantNodeName.FUNNEL_GENERATOR):
        builder = self._graph

        funnel_planner = FunnelPlannerNode(self._team)
        builder.add_node(AssistantNodeName.FUNNEL_PLANNER, funnel_planner.run)
        builder.add_conditional_edges(
            AssistantNodeName.FUNNEL_PLANNER,
            funnel_planner.router,
            path_map={
                "tools": AssistantNodeName.FUNNEL_PLANNER_TOOLS,
            },
        )

        funnel_planner_tools = FunnelPlannerToolsNode(self._team)
        builder.add_node(AssistantNodeName.FUNNEL_PLANNER_TOOLS, funnel_planner_tools.run)
        builder.add_conditional_edges(
            AssistantNodeName.FUNNEL_PLANNER_TOOLS,
            funnel_planner_tools.router,
            path_map={
                "continue": AssistantNodeName.FUNNEL_PLANNER,
                "plan_found": next_node,
            },
        )

        return self

    def add_funnel_generator(self, next_node: AssistantNodeName = AssistantNodeName.SUMMARIZER):
        builder = self._graph

        funnel_generator = FunnelGeneratorNode(self._team)
        builder.add_node(AssistantNodeName.FUNNEL_GENERATOR, funnel_generator.run)

        funnel_generator_tools = FunnelGeneratorToolsNode(self._team)
        builder.add_node(AssistantNodeName.FUNNEL_GENERATOR_TOOLS, funnel_generator_tools.run)

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

    def add_summarizer(self, next_node: AssistantNodeName = AssistantNodeName.END):
        builder = self._graph
        summarizer_node = SummarizerNode(self._team)
        builder.add_node(AssistantNodeName.SUMMARIZER, summarizer_node.run)
        builder.add_edge(AssistantNodeName.SUMMARIZER, next_node)
        return self

    def compile_full_graph(self):
        return (
            self.add_start()
            .add_router()
            .add_trends_planner()
            .add_trends_generator()
            .add_funnel_planner()
            .add_funnel_generator()
            .add_summarizer()
            .compile()
        )


class Assistant:
    _team: Team
    _graph: CompiledStateGraph

    def __init__(self, team: Team):
        self._team = team
        self._graph = AssistantGraph(team).compile_full_graph()

    def stream(self, conversation: Conversation) -> Generator[BaseModel, None, None]:
        callbacks = [langfuse_handler] if langfuse_handler else []
        messages = [message.root for message in conversation.messages]

        chunks = AIMessageChunk(content="")
        state: AssistantState = {"messages": messages, "intermediate_steps": None, "plan": None}

        generator: Iterator[Any] = self._graph.stream(
            state,
            config={"recursion_limit": 24, "callbacks": callbacks},
            stream_mode=["messages", "values", "updates"],
        )

        chunks = AIMessageChunk(content="")

        # Send a chunk to establish the connection avoiding the worker's timeout.
        yield AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)

        try:
            for update in generator:
                if is_state_update(update):
                    _, new_state = update
                    state = new_state

                elif is_value_update(update):
                    _, state_update = update

                    if (
                        AssistantNodeName.ROUTER in state_update
                        and "messages" in state_update[AssistantNodeName.ROUTER]
                    ):
                        yield state_update[AssistantNodeName.ROUTER]["messages"][0]
                    elif intersected_nodes := state_update.keys() & VISUALIZATION_NODES.keys():
                        # Reset chunks when schema validation fails.
                        chunks = AIMessageChunk(content="")

                        node_name = intersected_nodes.pop()
                        if "messages" in state_update[node_name]:
                            yield state_update[node_name]["messages"][0]
                        elif state_update[node_name].get("intermediate_steps", []):
                            yield AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)
                    elif AssistantNodeName.SUMMARIZER in state_update:
                        chunks = AIMessageChunk(content="")
                        yield state_update[AssistantNodeName.SUMMARIZER]["messages"][0]
                elif is_message_update(update):
                    langchain_message, langgraph_state = update[1]
                    if isinstance(langchain_message, AIMessageChunk):
                        if langgraph_state["langgraph_node"] in VISUALIZATION_NODES.keys():
                            chunks += langchain_message  # type: ignore
                            parsed_message = VISUALIZATION_NODES[langgraph_state["langgraph_node"]].parse_output(
                                chunks.tool_calls[0]["args"]
                            )
                            if parsed_message:
                                yield VisualizationMessage(
                                    reasoning_steps=parsed_message.reasoning_steps, answer=parsed_message.answer
                                )
                        elif langgraph_state["langgraph_node"] == AssistantNodeName.SUMMARIZER:
                            chunks += langchain_message  # type: ignore
                            yield AssistantMessage(content=chunks.content)
        except Exception as e:
            capture_exception(e)
            yield FailureMessage()  # This is an unhandled error, so we just stop further generation at this point
