from unittest.mock import MagicMock, patch

from ee.hogai.graph.filter_options.graph import FilterOptionsGraph
from ee.hogai.utils.types import AssistantNodeName
from posthog.test.base import BaseTest


class TestFilterOptionsGraph(BaseTest):
    def test_init(self):
        """Test that FilterOptionsGraph initializes correctly."""
        graph = FilterOptionsGraph(self.team, self.user)

        self.assertEqual(graph._team, self.team)
        self.assertEqual(graph._user, self.user)

    @patch("ee.hogai.graph.filter_options.graph.FilterOptionsNode")
    @patch("ee.hogai.graph.filter_options.graph.FilterOptionsToolsNode")
    def test_add_filter_options_generator_default_next_node(self, mock_tools_class, mock_node_class):
        """Test adding filter options generator with default next node."""
        graph = FilterOptionsGraph(self.team, self.user)

        # Mock the instances
        mock_tools_instance = MagicMock()
        mock_tools_instance.router = MagicMock()
        mock_tools_class.return_value = mock_tools_instance

        mock_node_instance = MagicMock()
        mock_node_class.return_value = mock_node_instance

        result = graph.add_filter_options_generator()

        # Verify the graph instance is returned for chaining
        self.assertIs(result, graph)
        self.assertTrue(graph._has_start_node)

        # Verify nodes were initialized with correct parameters
        mock_node_class.assert_called_once_with(self.team, self.user)
        mock_tools_class.assert_called_once_with(self.team, self.user)

    @patch("ee.hogai.graph.filter_options.graph.FilterOptionsNode")
    @patch("ee.hogai.graph.filter_options.graph.FilterOptionsToolsNode")
    def test_add_filter_options_generator_custom_next_node(self, mock_tools_class, mock_node_class):
        """Test adding filter options generator with custom next node."""
        graph = FilterOptionsGraph(self.team, self.user)
        custom_next_node = AssistantNodeName.ROOT

        # Mock the instances
        mock_tools_instance = MagicMock()
        mock_tools_instance.router = MagicMock()
        mock_tools_class.return_value = mock_tools_instance

        mock_node_instance = MagicMock()
        mock_node_class.return_value = mock_node_instance

        result = graph.add_filter_options_generator(next_node=custom_next_node)

        # Verify the graph instance is returned for chaining
        self.assertIs(result, graph)
        self.assertTrue(graph._has_start_node)

    def test_compile_full_graph(self):
        """Test that compile_full_graph calls add_filter_options_generator and compile."""
        graph = FilterOptionsGraph(self.team, self.user)

        with (
            patch.object(graph, "add_filter_options_generator") as mock_add_generator,
            patch.object(graph, "compile") as mock_compile,
        ):
            mock_add_generator.return_value = graph
            mock_compile.return_value = "compiled_graph"

            result = graph.compile_full_graph()

            # Verify add_filter_options_generator was called
            mock_add_generator.assert_called_once()

            # Verify compile was called
            mock_compile.assert_called_once()

            # Verify result
            self.assertEqual(result, "compiled_graph")

    def test_compile_full_graph_with_checkpointer(self):
        """Test that compile_full_graph passes checkpointer to compile."""
        graph = FilterOptionsGraph(self.team, self.user)
        checkpointer = MagicMock()

        with (
            patch.object(graph, "add_filter_options_generator") as mock_add_generator,
            patch.object(graph, "compile") as mock_compile,
        ):
            mock_add_generator.return_value = graph

            graph.compile_full_graph(checkpointer=checkpointer)

            # Verify compile was called with checkpointer
            mock_compile.assert_called_once_with(checkpointer=checkpointer)
