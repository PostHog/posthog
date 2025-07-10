from ee.hogai.utils.types import AssistantNodeName

from .nodes import FilterOptionsNode, FilterOptionsToolsNode
from ee.hogai.graph.graph import BaseAssistantGraph
from typing import Optional


class FilterOptionsGraph(BaseAssistantGraph):
    """Graph for generating filtering options based on user queries."""

    def __init__(self, team, user, injected_prompts: Optional[dict] = None):
        super().__init__(team, user)
        self.injected_prompts = injected_prompts or {}

    def add_filter_options_generator(self, next_node: AssistantNodeName = AssistantNodeName.END):
        """Add the filter options generator nodes to the graph."""
        builder = self._graph
        self._has_start_node = True

        # Add the main filter options node with injected prompts
        filter_options = FilterOptionsNode(self._team, self._user, injected_prompts=self.injected_prompts)
        builder.add_node(AssistantNodeName.FILTER_OPTIONS, filter_options)
        builder.add_edge(AssistantNodeName.START, AssistantNodeName.FILTER_OPTIONS)

        # Add the tools node
        filter_options_tools = FilterOptionsToolsNode(self._team, self._user)
        builder.add_node(AssistantNodeName.FILTER_OPTIONS_TOOLS, filter_options_tools)
        builder.add_edge(AssistantNodeName.FILTER_OPTIONS, AssistantNodeName.FILTER_OPTIONS_TOOLS)

        # Add conditional edges based on the tools node's router
        builder.add_conditional_edges(
            AssistantNodeName.FILTER_OPTIONS_TOOLS,
            filter_options_tools.router,
            {
                "continue": AssistantNodeName.FILTER_OPTIONS,
                "end": next_node,
            },
        )

        return self

    def compile_full_graph(self):
        """Compile a complete filter options graph."""
        return self.add_filter_options_generator().compile()
