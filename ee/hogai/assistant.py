from collections.abc import Generator
from typing import Any, Literal, TypedDict, TypeGuard, Union, cast

from langchain_core.messages import AIMessageChunk
from langfuse.callback import CallbackHandler
from langgraph.graph.state import StateGraph

from ee import settings
from ee.hogai.trends.nodes import (
    CreateTrendsPlanNode,
    CreateTrendsPlanToolsNode,
    GenerateTrendsNode,
    GenerateTrendsToolsNode,
)
from ee.hogai.utils import AssistantNodeName, AssistantState, Conversation
from posthog.models.team.team import Team
from posthog.schema import VisualizationMessage

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

        create_trends_plan_node = CreateTrendsPlanNode(self._team)
        builder.add_node(CreateTrendsPlanNode.name, create_trends_plan_node.run)

        create_trends_plan_tools_node = CreateTrendsPlanToolsNode(self._team)
        builder.add_node(CreateTrendsPlanToolsNode.name, create_trends_plan_tools_node.run)

        generate_trends_node = GenerateTrendsNode(self._team)
        builder.add_node(GenerateTrendsNode.name, generate_trends_node.run)

        generate_trends_tools_node = GenerateTrendsToolsNode(self._team)
        builder.add_node(GenerateTrendsToolsNode.name, generate_trends_tools_node.run)
        builder.add_edge(GenerateTrendsToolsNode.name, GenerateTrendsNode.name)

        builder.add_edge(AssistantNodeName.START, create_trends_plan_node.name)
        builder.add_conditional_edges(create_trends_plan_node.name, create_trends_plan_node.router)
        builder.add_conditional_edges(create_trends_plan_tools_node.name, create_trends_plan_tools_node.router)
        builder.add_conditional_edges(GenerateTrendsNode.name, generate_trends_node.router)

        return builder.compile()

    def stream(self, conversation: Conversation) -> Generator[str, None, None]:
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

        for update in generator:
            if is_state_update(update):
                _, new_state = update
                state = new_state

            elif is_value_update(update):
                _, state_update = update

                if AssistantNodeName.GENERATE_TRENDS in state_update:
                    # Reset chunks when schema validation fails.
                    chunks = AIMessageChunk(content="")

                    if "messages" in state_update[AssistantNodeName.GENERATE_TRENDS]:
                        message = cast(
                            VisualizationMessage, state_update[AssistantNodeName.GENERATE_TRENDS]["messages"][0]
                        )
                        yield message.model_dump_json()

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
                        ).model_dump_json()
