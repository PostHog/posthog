from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from ee.hogai.research_agent.graph import ResearchAgentGraph
from ee.hogai.research_agent.mode_manager import ResearchAgentModeManager
from ee.hogai.utils.types.base import AssistantGraphName, AssistantNodeName


class TestResearchAgentGraph(BaseTest):
    def test_graph_name_is_deep_research(self):
        graph = ResearchAgentGraph(self.team, self.user)

        self.assertEqual(graph.graph_name, AssistantGraphName.DEEP_RESEARCH)

    def test_mode_manager_class_returns_research_agent_mode_manager(self):
        graph = ResearchAgentGraph(self.team, self.user)

        self.assertEqual(graph.mode_manager_class, ResearchAgentModeManager)

    def test_add_title_generator_adds_node(self):
        graph = ResearchAgentGraph(self.team, self.user)

        mock_graph = MagicMock()
        graph._graph = mock_graph

        graph.add_title_generator()

        mock_graph.add_node.assert_called()
        node_name_arg = mock_graph.add_node.call_args[0][0]
        self.assertEqual(node_name_arg, AssistantNodeName.TITLE_GENERATOR)

    def test_add_title_generator_adds_edges(self):
        graph = ResearchAgentGraph(self.team, self.user)

        mock_graph = MagicMock()
        graph._graph = mock_graph

        graph.add_title_generator()

        # Should add edges from START to TITLE_GENERATOR and from TITLE_GENERATOR to END
        add_edge_calls = mock_graph.add_edge.call_args_list
        self.assertEqual(len(add_edge_calls), 2)

        # Check first edge: START -> TITLE_GENERATOR
        first_edge = add_edge_calls[0][0]
        self.assertEqual(first_edge[0], AssistantNodeName.START)
        self.assertEqual(first_edge[1], AssistantNodeName.TITLE_GENERATOR)

        # Check second edge: TITLE_GENERATOR -> END
        second_edge = add_edge_calls[1][0]
        self.assertEqual(second_edge[0], AssistantNodeName.TITLE_GENERATOR)
        self.assertEqual(second_edge[1], AssistantNodeName.END)

    def test_add_title_generator_sets_has_start_node(self):
        graph = ResearchAgentGraph(self.team, self.user)
        graph._graph = MagicMock()

        self.assertFalse(graph._has_start_node)

        graph.add_title_generator()

        self.assertTrue(graph._has_start_node)

    def test_add_title_generator_with_custom_end_node(self):
        graph = ResearchAgentGraph(self.team, self.user)

        mock_graph = MagicMock()
        graph._graph = mock_graph

        custom_end_node = AssistantNodeName.ROOT

        graph.add_title_generator(end_node=custom_end_node)

        add_edge_calls = mock_graph.add_edge.call_args_list
        second_edge = add_edge_calls[1][0]
        self.assertEqual(second_edge[1], custom_end_node)

    def test_add_title_generator_returns_self(self):
        graph = ResearchAgentGraph(self.team, self.user)
        graph._graph = MagicMock()

        result = graph.add_title_generator()

        self.assertIs(result, graph)

    def test_compile_full_graph_calls_methods_in_order(self):
        graph = ResearchAgentGraph(self.team, self.user)

        with (
            patch.object(graph, "add_agent_node", return_value=graph) as mock_add_agent,
            patch.object(graph, "add_agent_tools_node", return_value=graph) as mock_add_tools,
            patch.object(graph, "add_title_generator", return_value=graph) as mock_add_title,
            patch.object(graph, "compile", return_value=MagicMock()) as mock_compile,
        ):
            graph.compile_full_graph()

            mock_add_agent.assert_called_once_with(is_start_node=True)
            mock_add_tools.assert_called_once()
            mock_add_title.assert_called_once()
            mock_compile.assert_called_once_with(checkpointer=None)

    def test_compile_full_graph_with_checkpointer(self):
        graph = ResearchAgentGraph(self.team, self.user)
        mock_checkpointer = MagicMock()

        with (
            patch.object(graph, "add_agent_node", return_value=graph),
            patch.object(graph, "add_agent_tools_node", return_value=graph),
            patch.object(graph, "add_title_generator", return_value=graph),
            patch.object(graph, "compile", return_value=MagicMock()) as mock_compile,
        ):
            graph.compile_full_graph(checkpointer=mock_checkpointer)

            mock_compile.assert_called_once_with(checkpointer=mock_checkpointer)
