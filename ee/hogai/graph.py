from langgraph.graph.state import StateGraph

from ee.hogai.trends.nodes import CreateTrendsPlanNode, CreateTrendsPlanToolsNode, GenerateTrendsNode
from ee.hogai.utils import AssistantNodeName, AssistantState
from posthog.models.team.team import Team


class AssistantGraph:
    _team: Team
    _graph: StateGraph

    def __init__(self, team: Team):
        self._team = team

    def _build_graph(self):
        builder = StateGraph(AssistantState)

        builder.add_node(AssistantNodeName.CREATE_TRENDS_PLAN, CreateTrendsPlanNode.run)
        builder.add_node(AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS, CreateTrendsPlanToolsNode.run)
        builder.add_node(AssistantNodeName.GENERATE_TRENDS, GenerateTrendsNode.run)

        builder.add_edge(AssistantNodeName.START, AssistantNodeName.CREATE_TRENDS_PLAN)

        builder.add_conditional_edges(AssistantNodeName.CREATE_TRENDS_PLAN, CreateTrendsPlanNode.router)

        builder.add_edge(AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS, AssistantNodeName.CREATE_TRENDS_PLAN)

        builder.add_edge(AssistantNodeName.GENERATE_TRENDS, AssistantNodeName.END)

        return builder.compile()

    def stream(self, user_input: str):
        assistant_graph = self._build_graph()
        return assistant_graph.stream({"messages": [("user", user_input)], "team": self._team, "chain_of_thought": []})
