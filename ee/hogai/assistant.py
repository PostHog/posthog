from collections.abc import Generator
from typing import cast

from langchain_core.messages import AIMessageChunk
from langfuse.callback import CallbackHandler
from langgraph.graph.state import StateGraph

from ee import settings
from ee.hogai.trends.nodes import CreateTrendsPlanNode, CreateTrendsPlanToolsNode, GenerateTrendsNode
from ee.hogai.utils import AssistantNodeName, AssistantState, Conversation
from posthog.models.team.team import Team
from posthog.schema import VisualizationMessage

if settings.LANGFUSE_PUBLIC_KEY:
    langfuse_handler = CallbackHandler(
        public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY, host=settings.LANGFUSE_HOST
    )
else:
    langfuse_handler = None


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

        builder.add_edge(AssistantNodeName.START, create_trends_plan_node.name)
        builder.add_conditional_edges(create_trends_plan_node.name, create_trends_plan_node.router)
        builder.add_conditional_edges(create_trends_plan_tools_node.name, create_trends_plan_tools_node.router)
        builder.add_conditional_edges(GenerateTrendsNode.name, generate_trends_node.router)

        return builder.compile()

    def stream(self, conversation: Conversation) -> Generator[str, None, None]:
        assistant_graph = self._compile_graph()
        callbacks = [langfuse_handler] if langfuse_handler else []

        generator = assistant_graph.stream(
            {"messages": conversation.messages},
            config={"recursion_limit": 24, "callbacks": callbacks},
            stream_mode="messages",
        )

        chunks = AIMessageChunk(content="")

        for message, state in generator:
            if state["langgraph_node"] == AssistantNodeName.GENERATE_TRENDS:
                if isinstance(message, VisualizationMessage):
                    yield message.model_dump_json()
                elif isinstance(message, AIMessageChunk):
                    message = cast(AIMessageChunk, message)
                    chunks += message  # type: ignore
                    parsed_message = GenerateTrendsNode.parse_output(chunks.tool_calls[0]["args"])
                    if parsed_message:
                        yield VisualizationMessage(
                            reasoning_steps=parsed_message.reasoning_steps, answer=parsed_message.answer
                        ).model_dump_json()
