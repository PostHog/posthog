from typing import Generic

from posthog.models import Team, User

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.base import BaseAssistantGraph
from ee.hogai.utils.types import PartialStateType, StateType
from ee.hogai.utils.types.base import AssistantGraphName, NodePath

from .nodes import StateClassMixin, TaxonomyAgentNode, TaxonomyAgentToolsNode
from .toolkit import TaxonomyAgentToolkit
from .types import TaxonomyNodeName


class TaxonomyAgent(
    BaseAssistantGraph[StateType, PartialStateType], Generic[StateType, PartialStateType], StateClassMixin
):
    """Taxonomy agent that can be configured with different node classes."""

    def __init__(
        self,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...],
        loop_node_class: type["TaxonomyAgentNode"],
        tools_node_class: type["TaxonomyAgentToolsNode"],
        toolkit_class: type["TaxonomyAgentToolkit"],
    ):
        super().__init__(team, user, node_path)
        self._loop_node_class = loop_node_class
        self._tools_node_class = tools_node_class
        self._toolkit_class = toolkit_class

    @property
    def state_type(self) -> type[StateType]:
        # Extract the State type from the generic parameter
        state_type, _ = self._get_state_class(TaxonomyAgent)
        return state_type

    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.TAXONOMY

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        """Compile a complete taxonomy graph."""
        return self.add_taxonomy_generator().compile(checkpointer=checkpointer)

    def add_taxonomy_generator(self, next_node: TaxonomyNodeName = TaxonomyNodeName.END):
        """Add the taxonomy generator nodes to the graph."""
        self._has_start_node = True

        # Add the main loop node
        loop_node = self._loop_node_class(self._team, self._user, self._toolkit_class)
        self.add_node(TaxonomyNodeName.LOOP_NODE, loop_node)
        self._graph.add_edge(TaxonomyNodeName.START, TaxonomyNodeName.LOOP_NODE)

        # Add the tools node
        tools_node = self._tools_node_class(self._team, self._user, self._toolkit_class)
        self.add_node(TaxonomyNodeName.TOOLS_NODE, tools_node)
        self._graph.add_edge(TaxonomyNodeName.LOOP_NODE, TaxonomyNodeName.TOOLS_NODE)

        # Add conditional edges based on the tools node's router
        self._graph.add_conditional_edges(
            TaxonomyNodeName.TOOLS_NODE,
            tools_node.router,
            {
                "continue": TaxonomyNodeName.LOOP_NODE,
                "end": next_node,
            },
        )

        return self
