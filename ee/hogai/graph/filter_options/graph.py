from .types import FilterOptionsState

from .nodes import FilterOptionsNode, FilterOptionsToolsNode

from ee.hogai.graph.taxonomy_toolkit import TaxonomyAgent


class FilterOptionsGraph(TaxonomyAgent[FilterOptionsState]):
    """Graph for generating filtering options based on user queries."""

    def __init__(self, team, user):
        super().__init__(team, user, FilterOptionsNode, FilterOptionsToolsNode)

    # def add_filter_options_generator(self, next_node: AssistantNodeName = AssistantNodeName.END):
    #     """Add the filter options generator nodes to the graph."""
    #     builder = self._graph
    #     self._has_start_node = True

    #     # Add the main filter options node
    #     filter_options = FilterOptionsNode(self._team, self._user)
    #     builder.add_node(FilterOptionsNodeName.FILTER_OPTIONS, filter_options)
    #     builder.add_edge(AssistantNodeName.START, FilterOptionsNodeName.FILTER_OPTIONS)

    #     # Add the tools node
    #     filter_options_tools = FilterOptionsToolsNode(self._team, self._user)
    #     builder.add_node(FilterOptionsNodeName.FILTER_OPTIONS_TOOLS, filter_options_tools)
    #     builder.add_edge(FilterOptionsNodeName.FILTER_OPTIONS, FilterOptionsNodeName.FILTER_OPTIONS_TOOLS)

    #     # Add conditional edges based on the tools node's router
    #     builder.add_conditional_edges(
    #         FilterOptionsNodeName.FILTER_OPTIONS_TOOLS,
    #         filter_options_tools.router,
    #         {
    #             "continue": FilterOptionsNodeName.FILTER_OPTIONS,
    #             "end": next_node,
    #         },
    #     )

    #     return self

    # def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
    #     """Compile a complete filter options graph."""
    #     return self.add_filter_options_generator().compile(checkpointer=checkpointer)
