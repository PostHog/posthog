from typing import Generic
from .nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode, StateClassMixin
from .toolkit import TaxonomyAgentToolkit
from posthog.models import Team, User
from .types import TaxonomyNodeName
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import StateType, PartialStateType
from ee.hogai.graph.graph import BaseAssistantGraph


class TaxonomyAgent(BaseAssistantGraph[StateType], Generic[StateType, PartialStateType], StateClassMixin):
    """Taxonomy agent that can be configured with different node classes."""

    def __init__(
        self,
        team: Team,
        user: User,
        loop_node_class: type["TaxonomyAgentNode"],
        tools_node_class: type["TaxonomyAgentToolsNode"],
        toolkit_class: type["TaxonomyAgentToolkit"],
    ):
        # Extract the State type from the generic parameter
        state_class, _ = self._get_state_class(TaxonomyAgent)
        super().__init__(team, user, state_class)

        self._loop_node_class = loop_node_class
        self._tools_node_class = tools_node_class
        self._toolkit_class = toolkit_class

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
