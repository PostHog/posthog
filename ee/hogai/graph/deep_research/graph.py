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
        self._has_start_node = False

    def add_agent_subgraph_executor(self, next_node: AssistantNodeName = AssistantNodeName.END) -> "DeepResearchGraph":
        """
        Add the agent subgraph executor.

        Uses the AgentSubgraph directly as a compiled subgraph following
        the established pattern in the codebase.
        """
        # Create and compile the subgraph following established patterns
        agent_subgraph = AgentSubgraph(self._team, self._user)
        compiled_subgraph = agent_subgraph.compile_full_graph()

        # Add the compiled subgraph as a node
        self._graph.add_node(AssistantNodeName.AGENT_SUBGRAPH_EXECUTOR, compiled_subgraph)
        self._graph.add_edge(AssistantNodeName.AGENT_SUBGRAPH_EXECUTOR, next_node)

        return self

    def add_planner(
        self, next_node: AssistantNodeName = AssistantNodeName.AGENT_SUBGRAPH_EXECUTOR
    ) -> "DeepResearchGraph":
        """
        Add the planner node that parses DEEP_RESEARCH commands.
        """
        planner_node = DeepResearchPlannerNode(self._team, self._user)
        self._graph.add_node(AssistantNodeName.DEEP_RESEARCH, planner_node)

        # Add conditional routing from planner
        self._graph.add_conditional_edges(
            AssistantNodeName.DEEP_RESEARCH,
            planner_node.router,
            path_map={"execute": next_node, "end": AssistantNodeName.END},
        )

        return self

    def add_start_edge(self) -> "DeepResearchGraph":
        """Add the start edge to the planner."""
        self._has_start_node = True
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.DEEP_RESEARCH)
        return self

    def compile_full_graph(self, checkpointer: Optional[DjangoCheckpointer] = None):
        """
        Compile the deep research graph.

        Creates a graph that can:
        - Accept research steps
        - Execute them via AgentSubgraphNode
        - Handle both single and parallel execution
        """
        self.add_start_edge()
        self.add_planner()
        self.add_agent_subgraph_executor()

        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")

        return self._graph.compile(checkpointer=checkpointer or _default_checkpointer)
