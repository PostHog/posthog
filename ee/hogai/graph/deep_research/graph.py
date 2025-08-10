from typing import Optional

from langgraph.graph.state import StateGraph

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.deep_research.agent_subgraph.graph import AgentSubgraph
from ee.hogai.graph.deep_research.planner_node import DeepResearchPlannerNode
from ee.hogai.utils.types import (
    AssistantNodeName,
    AgentSubgraphState,
)
from posthog.models import Team, User

# Use a default checkpointer instance
_default_checkpointer = DjangoCheckpointer()


class DeepResearchGraph:
    """
    Deep Research Graph for executing research plans with multiple steps.

    This graph is designed to handle complex research workflows where:
    - A planner creates multiple research steps (TODOs)
    - Each step can be executed independently or in parallel
    - Steps can reference artifacts from other steps
    - Results are aggregated for final reporting
    """

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user
        self._graph = StateGraph(AgentSubgraphState)

    def compile_full_graph(self, checkpointer: Optional[DjangoCheckpointer] = None):
        """
        Compile the deep research graph.

        Creates a graph that can:
        - Accept research steps
        - Execute them via AgentSubgraphNode
        """
        planner_node = DeepResearchPlannerNode(self._team, self._user)
        agent_subgraph = AgentSubgraph(self._team, self._user)
        compiled_subgraph = agent_subgraph.compile_full_graph()

        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.DEEP_RESEARCH)

        self._graph.add_node(AssistantNodeName.DEEP_RESEARCH, planner_node)
        self._graph.add_conditional_edges(
            AssistantNodeName.DEEP_RESEARCH,
            planner_node.router,
            path_map={"execute": AssistantNodeName.AGENT_SUBGRAPH_EXECUTOR, "end": AssistantNodeName.END},
        )

        self._graph.add_node(AssistantNodeName.AGENT_SUBGRAPH_EXECUTOR, compiled_subgraph)
        self._graph.add_edge(AssistantNodeName.AGENT_SUBGRAPH_EXECUTOR, AssistantNodeName.DEEP_RESEARCH)

        return self._graph.compile(checkpointer=checkpointer or _default_checkpointer)
