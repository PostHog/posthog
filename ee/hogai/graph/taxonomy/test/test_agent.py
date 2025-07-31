from unittest.mock import Mock, patch

from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState, PartialTaxonomyAgentState, TaxonomyNodeName
from posthog.test.base import BaseTest


class MockTaxonomyAgentNode(TaxonomyAgentNode[TaxonomyAgentState, PartialTaxonomyAgentState]):
    def get_system_prompts(self):
        return ["test system prompt"]


class MockTaxonomyAgentToolsNode(TaxonomyAgentToolsNode[TaxonomyAgentState, PartialTaxonomyAgentState]):
    pass


class MockTaxonomyAgentToolkit(TaxonomyAgentToolkit):
    def get_tools(self):
        return []


class ConcreteTaxonomyAgent(TaxonomyAgent[TaxonomyAgentState, PartialTaxonomyAgentState]):
    pass


class TestTaxonomyAgent(BaseTest):
    @patch("ee.hogai.graph.taxonomy.agent.StateGraph")
    def setUp(self, mock_state_graph):
        super().setUp()
        mock_graph = Mock()
        mock_state_graph.return_value = mock_graph

        self.agent = ConcreteTaxonomyAgent(
            team=self.team,
            user=self.user,
            loop_node_class=MockTaxonomyAgentNode,
            tools_node_class=MockTaxonomyAgentToolsNode,
            toolkit_class=MockTaxonomyAgentToolkit,
        )

    def test_agent_initialization(self):
        self.assertEqual(self.agent._team, self.team)
        self.assertEqual(self.agent._user, self.user)
        self.assertEqual(self.agent._loop_node_class, MockTaxonomyAgentNode)
        self.assertEqual(self.agent._tools_node_class, MockTaxonomyAgentToolsNode)
        self.assertEqual(self.agent._toolkit_class, MockTaxonomyAgentToolkit)
        self.assertFalse(self.agent._has_start_node)

    def test_get_state_class(self):
        state_class, partial_state_class = self.agent._get_state_class()
        self.assertEqual(state_class, TaxonomyAgentState)
        self.assertEqual(partial_state_class, PartialTaxonomyAgentState)

    def test_get_state_class_no_generic(self):
        # Create an agent without proper generic typing to test error case
        class NonGenericAgent(TaxonomyAgent):
            pass

        with self.assertRaises(ValueError) as context:
            NonGenericAgent(
                team=self.team,
                user=self.user,
                loop_node_class=MockTaxonomyAgentNode,
                tools_node_class=MockTaxonomyAgentToolsNode,
                toolkit_class=MockTaxonomyAgentToolkit,
            )

        self.assertIn("Could not determine state type", str(context.exception))

    def test_add_edge(self):
        result = self.agent.add_edge("START", "test_node")
        self.assertEqual(result, self.agent)
        self.assertTrue(self.agent._has_start_node)

    def test_add_edge_non_start(self):
        result = self.agent.add_edge("node1", "node2")
        self.assertEqual(result, self.agent)
        self.assertFalse(self.agent._has_start_node)

    def test_add_node(self):
        mock_action = Mock()
        result = self.agent.add_node("test_node", mock_action)
        self.assertEqual(result, self.agent)

    def test_add_conditional_edges(self):
        mock_router = Mock()
        path_map = {"continue": "loop", "end": "END"}
        result = self.agent.add_conditional_edges("test_node", mock_router, path_map)
        self.assertEqual(result, self.agent)

    def test_compile_without_start_node(self):
        with self.assertRaises(ValueError) as context:
            self.agent.compile()

        self.assertIn("Start node not added", str(context.exception))

    def test_compile_with_start_node(self):
        self.agent._has_start_node = True
        _ = self.agent.compile()

        self.agent._graph.compile.assert_called_once_with(checkpointer=None)

    def test_compile_with_checkpointer(self):
        mock_checkpointer = Mock()
        self.agent._has_start_node = True
        _ = self.agent.compile(checkpointer=mock_checkpointer)

        self.agent._graph.compile.assert_called_once_with(checkpointer=mock_checkpointer)

    def test_compile_full_graph(self):
        _ = self.agent.compile_full_graph()

        self.agent._graph.compile.assert_called_once_with(checkpointer=None)

    def test_compile_full_graph_with_checkpointer(self):
        mock_checkpointer = Mock()
        _ = self.agent.compile_full_graph(checkpointer=mock_checkpointer)

        self.agent._graph.compile.assert_called_once_with(checkpointer=mock_checkpointer)

    def test_add_taxonomy_generator(self):
        _ = self.agent.add_taxonomy_generator()

        self.assertEqual(len(self.agent._graph.add_node.call_args_list), 2)

        self.assertEqual(len(self.agent._graph.add_edge.call_args_list), 2)

        self.agent._graph.add_conditional_edges.assert_called_once()

    def test_add_taxonomy_generator_custom_next_node(self):
        custom_next = "custom_end"
        _ = self.agent.add_taxonomy_generator(next_node=custom_next)

        conditional_call = self.agent._graph.add_conditional_edges.call_args
        self.assertEqual(conditional_call[0][0], TaxonomyNodeName.TOOLS_NODE)
        self.assertEqual(conditional_call[0][2]["end"], custom_next)

    def test_node_instantiation_in_add_taxonomy_generator(self):
        with (
            patch.object(MockTaxonomyAgentNode, "__init__", return_value=None) as mock_loop_init,
            patch.object(MockTaxonomyAgentToolsNode, "__init__", return_value=None) as mock_tools_init,
        ):
            self.agent.add_taxonomy_generator()

        mock_loop_init.assert_called_once_with(self.team, self.user, MockTaxonomyAgentToolkit)
        mock_tools_init.assert_called_once_with(self.team, self.user, MockTaxonomyAgentToolkit)
