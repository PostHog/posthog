from .types import TaxonomyAgentState, PartialTaxonomyAgentState

from .nodes import FilterOptionsNode, FilterOptionsToolsNode

from ee.hogai.graph.taxonomy import TaxonomyAgent
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit


class FilterOptionsGraph(TaxonomyAgent[TaxonomyAgentState, PartialTaxonomyAgentState]):
    """Graph for generating filtering options based on user queries."""

    def __init__(
        self,
        team,
        user,
        toolkit_class: type[TaxonomyAgentToolkit],
        loop_node_class: type[FilterOptionsNode],
        tools_node_class: type[FilterOptionsToolsNode],
    ):
        super().__init__(
            team, user, toolkit_class=toolkit_class, loop_node_class=loop_node_class, tools_node_class=tools_node_class
        )
