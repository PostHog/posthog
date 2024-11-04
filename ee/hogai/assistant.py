from collections.abc import Generator
from typing import Any, Literal, TypedDict, TypeGuard, Union

from langchain_core.messages import AIMessageChunk
from langfuse.callback import CallbackHandler
from langgraph.graph.state import StateGraph
from pydantic import BaseModel

from ee import settings
from ee.hogai.router.nodes import RouterNode
from ee.hogai.trends.nodes import (
    CreateTrendsPlanNode,
    CreateTrendsPlanToolsNode,
    GenerateTrendsNode,
    GenerateTrendsToolsNode,
)
from ee.hogai.utils import AssistantNodeName, AssistantState, Conversation
from posthog.models.team.team import Team
from posthog.schema import (
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    VisualizationMessage,
)

if settings.LANGFUSE_PUBLIC_KEY:
    langfuse_handler = CallbackHandler(
        public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY, host=settings.LANGFUSE_HOST
    )
else:
    langfuse_handler = None


def is_value_update(update: list[Any]) -> TypeGuard[tuple[Literal["values"], dict[AssistantNodeName, Any]]]:
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
            path_map={"trends": AssistantNodeName.CREATE_TRENDS_PLAN},
        )

        create_trends_plan_node = CreateTrendsPlanNode(self._team)
        builder.add_node(AssistantNodeName.CREATE_TRENDS_PLAN, create_trends_plan_node.run)
        builder.add_conditional_edges(
            AssistantNodeName.CREATE_TRENDS_PLAN,
            create_trends_plan_node.router,
            path_map={
                "tools": AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS,
            },
        )

        create_trends_plan_tools_node = CreateTrendsPlanToolsNode(self._team)
        builder.add_node(AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS, create_trends_plan_tools_node.run)
        builder.add_conditional_edges(
            AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS,
            create_trends_plan_tools_node.router,
            path_map={
                "continue": AssistantNodeName.CREATE_TRENDS_PLAN,
                "next": AssistantNodeName.GENERATE_TRENDS,
            },
        )

        generate_trends_node = GenerateTrendsNode(self._team)
        builder.add_node(AssistantNodeName.GENERATE_TRENDS, generate_trends_node.run)

        generate_trends_tools_node = GenerateTrendsToolsNode(self._team)
        builder.add_node(AssistantNodeName.GENERATE_TRENDS_TOOLS, generate_trends_tools_node.run)

        builder.add_edge(AssistantNodeName.GENERATE_TRENDS_TOOLS, AssistantNodeName.GENERATE_TRENDS)
        builder.add_conditional_edges(
            AssistantNodeName.GENERATE_TRENDS,
            generate_trends_node.router,
            path_map={
                "tools": AssistantNodeName.GENERATE_TRENDS_TOOLS,
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
                elif AssistantNodeName.GENERATE_TRENDS in state_update:
                    # Reset chunks when schema validation fails.
                    chunks = AIMessageChunk(content="")

                    if "messages" in state_update[AssistantNodeName.GENERATE_TRENDS]:
                        yield state_update[AssistantNodeName.GENERATE_TRENDS]["messages"][0]
                    elif state_update[AssistantNodeName.GENERATE_TRENDS].get("intermediate_steps", []):
                        yield AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)

            elif is_message_update(update):
                langchain_message, langgraph_state = update[1]
                if langgraph_state["langgraph_node"] == AssistantNodeName.GENERATE_TRENDS and isinstance(
                    langchain_message, AIMessageChunk
                ):
                    chunks += langchain_message  # type: ignore
                    parsed_message = GenerateTrendsNode.parse_output(chunks.tool_calls[0]["args"])
                    if parsed_message:
                        yield VisualizationMessage(
                            reasoning_steps=parsed_message.reasoning_steps, answer=parsed_message.answer
                        )
