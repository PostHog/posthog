from unittest.mock import MagicMock, patch

from ee.hogai.graph.filter_options.graph import FilterOptionsGraph
from ee.hogai.utils.types import AssistantNodeName
from posthog.test.base import BaseTest


class TestFilterOptionsGraph(BaseTest):
    def test_init_without_injected_prompts(self):
        """Test that FilterOptionsGraph initializes correctly without injected prompts."""
        graph = FilterOptionsGraph(self.team, self.user)

        self.assertEqual(graph._team, self.team)
        self.assertEqual(graph._user, self.user)
        self.assertEqual(graph.injected_prompts, {})

    def test_init_with_injected_prompts(self):
        """Test that FilterOptionsGraph initializes correctly with injected prompts."""
        injected_prompts = {
            "product_description_prompt": "Custom product description",
            "examples_prompt": "Custom examples",
        }
        graph = FilterOptionsGraph(self.team, self.user, injected_prompts=injected_prompts)

        self.assertEqual(graph._team, self.team)
        self.assertEqual(graph._user, self.user)
        self.assertEqual(graph.injected_prompts, injected_prompts)

    def test_init_with_none_injected_prompts(self):
        """Test that FilterOptionsGraph handles None injected prompts correctly."""
        graph = FilterOptionsGraph(self.team, self.user, injected_prompts=None)

        self.assertEqual(graph.injected_prompts, {})

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
        mock_node_class.assert_called_once_with(self.team, self.user, injected_prompts={})
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

    @patch("ee.hogai.graph.filter_options.graph.FilterOptionsNode")
    @patch("ee.hogai.graph.filter_options.graph.FilterOptionsToolsNode")
    def test_add_filter_options_generator_with_injected_prompts(self, mock_tools_class, mock_node_class):
        """Test that injected prompts are passed to FilterOptionsNode."""
        injected_prompts = {"test_prompt": "test_value"}
        graph = FilterOptionsGraph(self.team, self.user, injected_prompts=injected_prompts)

        # Mock the instances
        mock_tools_instance = MagicMock()
        mock_tools_instance.router = MagicMock()
        mock_tools_class.return_value = mock_tools_instance

        mock_node_instance = MagicMock()
        mock_node_class.return_value = mock_node_instance

        graph.add_filter_options_generator()

        # Verify FilterOptionsNode was initialized with injected prompts
        mock_node_class.assert_called_once_with(self.team, self.user, injected_prompts=injected_prompts)
