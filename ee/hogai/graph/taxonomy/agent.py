from typing import Generic, get_args, get_origin
from .nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from .toolkit import TaxonomyAgentToolkit
from posthog.models import Team, User
from langgraph.graph import StateGraph
from .types import TaxonomyNodeName
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import StateType, PartialStateType


class TaxonomyAgent(Generic[StateType, PartialStateType]):
    """Taxonomy agent that can be configured with different node classes."""

    def __init__(
        self,
        team: Team,
        user: User,
        loop_node_class: type["TaxonomyAgentNode"],
        tools_node_class: type["TaxonomyAgentToolsNode"],
        toolkit_class: type["TaxonomyAgentToolkit"],
    ):
        self._team = team
        self._user = user
        self._loop_node_class = loop_node_class
        self._tools_node_class = tools_node_class
        self._toolkit_class = toolkit_class

        # Extract the State type from the generic parameter
        state_class, _ = self._get_state_class()
        self._graph = StateGraph(state_class)
        self._has_start_node = False

    def _get_state_class(self) -> tuple[type, type]:
        """Extract the State type from the class's generic parameters."""
        # Check if this class has generic arguments
        if hasattr(self.__class__, "__orig_bases__"):
            for base in self.__class__.__orig_bases__:
                if get_origin(base) is TaxonomyAgent:
                    args = get_args(base)
                    if args:
                        return args[0], args[1]  # State is the first argument and PartialState is the second argument

        # No generic type found - this shouldn't happen in proper usage
        raise ValueError(
            f"Could not determine state type for {self.__class__.__name__}. "
            "Make sure to inherit from TaxonomyAgent with a specific state type, "
            "e.g., TaxonomyAgent[TaxonomyAgentState]"
        )

    def add_edge(self, from_node: str, to_node: str):
        if from_node == "START":
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: str, action):
        self._graph.add_node(node, action)
        return self

    def add_conditional_edges(self, node: str, router, path_map: dict):
        self._graph.add_conditional_edges(node, router, path_map)
        return self

    def compile(self, checkpointer=None):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        return self._graph.compile(checkpointer=checkpointer)

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        """Compile a complete taxonomy graph."""
        return self.add_taxonomy_generator().compile(checkpointer=checkpointer)

    def add_taxonomy_generator(self, next_node: TaxonomyNodeName = TaxonomyNodeName.END):
        """Add the taxonomy generator nodes to the graph."""
        builder = self._graph
        self._has_start_node = True

        # Add the main loop node
        loop_node = self._loop_node_class(self._team, self._user, self._toolkit_class)
        builder.add_node(TaxonomyNodeName.LOOP_NODE, loop_node)
        builder.add_edge(TaxonomyNodeName.START, TaxonomyNodeName.LOOP_NODE)

        # Add the tools node
        tools_node = self._tools_node_class(self._team, self._user, self._toolkit_class)
        builder.add_node(TaxonomyNodeName.TOOLS_NODE, tools_node)
        builder.add_edge(TaxonomyNodeName.LOOP_NODE, TaxonomyNodeName.TOOLS_NODE)

        # Add conditional edges based on the tools node's router
        builder.add_conditional_edges(
            TaxonomyNodeName.TOOLS_NODE,
            tools_node.router,
            {
                "continue": TaxonomyNodeName.LOOP_NODE,
                "end": next_node,
            },
        )

        return self
