from collections.abc import Generator
from typing import Any, Literal, TypedDict, TypeGuard, Union

from langchain_core.globals import set_debug, set_verbose
from langchain_core.messages import AIMessageChunk
from langfuse.callback import CallbackHandler
from langgraph.graph.state import StateGraph
from pydantic import BaseModel

from ee import settings
from ee.hogai.funnels.nodes import (
    FunnelGeneratorNode,
    FunnelGeneratorToolsNode,
    FunnelPlannerNode,
    FunnelPlannerToolsNode,
)
from ee.hogai.router.nodes import RouterNode
from ee.hogai.schema_generator.nodes import SchemaGeneratorNode
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
    VisualizationMessage,
)

set_debug(True)
set_verbose(True)

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


class Assistant:
    _team: Team
    _graph: StateGraph

    def __init__(self, team: Team):
        self._team = team
        self._graph = StateGraph(AssistantState)

    def _compile_graph(self):
        builder = self._graph

        router_node = RouterNode(self._team)
        builder.add_node(AssistantNodeName.ROUTER, router_node.run)
        builder.add_edge(AssistantNodeName.START, AssistantNodeName.ROUTER)
        builder.add_conditional_edges(
            AssistantNodeName.ROUTER,
            router_node.router,
            path_map={"trends": AssistantNodeName.TRENDS_PLANNER, "funnel": AssistantNodeName.FUNNEL_PLANNER},
        )

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
                "plan_found": AssistantNodeName.TRENDS_GENERATOR,
            },
        )

        generate_trends_node = TrendsGeneratorNode(self._team)
        builder.add_node(AssistantNodeName.TRENDS_GENERATOR, generate_trends_node.run)

        generate_trends_tools_node = TrendsGeneratorToolsNode(self._team)
        builder.add_node(AssistantNodeName.TRENDS_GENERATOR_TOOLS, generate_trends_tools_node.run)

        builder.add_edge(AssistantNodeName.TRENDS_GENERATOR_TOOLS, AssistantNodeName.TRENDS_GENERATOR)
        builder.add_conditional_edges(
            AssistantNodeName.TRENDS_GENERATOR,
            generate_trends_node.router,
            path_map={
                "tools": AssistantNodeName.TRENDS_GENERATOR_TOOLS,
                "next": AssistantNodeName.END,
            },
        )

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
                "plan_found": AssistantNodeName.FUNNEL_GENERATOR,
            },
        )

        funnel_generator = FunnelGeneratorNode(self._team)
        builder.add_node(AssistantNodeName.FUNNEL_GENERATOR, funnel_generator.run)

        funnel_generator_tools_node = FunnelGeneratorToolsNode(self._team)
        builder.add_node(AssistantNodeName.FUNNEL_GENERATOR_TOOLS, funnel_generator_tools_node.run)

        builder.add_edge(AssistantNodeName.FUNNEL_GENERATOR_TOOLS, AssistantNodeName.FUNNEL_GENERATOR)
        builder.add_conditional_edges(
            AssistantNodeName.FUNNEL_GENERATOR,
            generate_trends_node.router,
            path_map={
                "tools": AssistantNodeName.FUNNEL_GENERATOR_TOOLS,
                "next": AssistantNodeName.END,
            },
        )

        return builder.compile()

    def stream(self, conversation: Conversation) -> Generator[BaseModel, None, None]:
        assistant_graph = self._compile_graph()
        callbacks = [langfuse_handler] if langfuse_handler else []
        messages = [message.root for message in conversation.messages]

        chunks = AIMessageChunk(content="")
        state: AssistantState = {"messages": messages, "intermediate_steps": None, "plan": None}
        visualization_nodes: dict[AssistantNodeName, type[SchemaGeneratorNode]] = {
            AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
            AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
        }

        generator = assistant_graph.stream(
            state,
            config={"recursion_limit": 24, "callbacks": callbacks},
            stream_mode=["messages", "values", "updates"],
        )

        chunks = AIMessageChunk(content="")

        # Send a chunk to establish the connection avoiding the worker's timeout.
        yield AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)

        for update in generator:
            if is_state_update(update):
                _, new_state = update
                state = new_state

            elif is_value_update(update):
                _, state_update = update

                if AssistantNodeName.ROUTER in state_update and "messages" in state_update[AssistantNodeName.ROUTER]:
                    yield state_update[AssistantNodeName.ROUTER]["messages"][0]
                elif state_update.keys() & visualization_nodes.keys():
                    # Reset chunks when schema validation fails.
                    chunks = AIMessageChunk(content="")

                    for node_name in visualization_nodes.keys():
                        if node_name not in state_update:
                            continue
                        if "messages" in state_update[node_name]:
                            yield state_update[node_name]["messages"][0]
                        elif state_update[node_name].get("intermediate_steps", []):
                            yield AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)

            elif is_message_update(update):
                langchain_message, langgraph_state = update[1]
                for node_name, viz_node in visualization_nodes.items():
                    if langgraph_state["langgraph_node"] == node_name and isinstance(langchain_message, AIMessageChunk):
                        chunks += langchain_message  # type: ignore
                        parsed_message = viz_node.parse_output(chunks.tool_calls[0]["args"])
                        if parsed_message:
                            yield VisualizationMessage(
                                reasoning_steps=parsed_message.reasoning_steps, answer=parsed_message.answer
                            )
