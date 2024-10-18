from collections.abc import Generator
from typing import cast

from langchain_core.messages import AIMessageChunk, BaseMessage
from langgraph.graph.state import StateGraph

from ee.hogai.trends.nodes import CreateTrendsPlanNode, CreateTrendsPlanToolsNode, GenerateTrendsNode
from ee.hogai.utils import AssistantMessage, AssistantNodeName, AssistantState
from posthog.models.team.team import Team
from posthog.schema import VisualizationMessagePayload


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

    def stream(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        assistant_graph = self._compile_graph()
        generator = assistant_graph.stream(
            {"messages": messages},
            config={"recursion_limit": 24},
            stream_mode="messages",
        )

        chunks = AIMessageChunk("")

        for message, state in generator:
            if state["langgraph_node"] == AssistantNodeName.GENERATE_TRENDS:
                if isinstance(message, AssistantMessage):
                    yield message.model_dump_json()
                elif isinstance(message, AIMessageChunk):
                    message = cast(AIMessageChunk, message)
                    chunks += message
                    parsed_message = GenerateTrendsNode.parse_output(chunks.tool_calls[0]["args"])
                    if parsed_message:
                        yield AssistantMessage(
                            type="ai",
                            content=parsed_message.model_dump_json(),
                            payload=VisualizationMessagePayload(plan=""),
                        ).model_dump_json()
