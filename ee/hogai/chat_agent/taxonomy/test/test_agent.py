from typing import cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from ee.hogai.chat_agent.taxonomy.agent import TaxonomyAgent
from ee.hogai.chat_agent.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.chat_agent.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.chat_agent.taxonomy.types import TaxonomyAgentState, TaxonomyNodeName
from ee.hogai.utils.types.composed import MaxNodeName


class MockTaxonomyAgentNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState]):
    def _get_system_prompt(self):
        return ["test system prompt"]


class MockTaxonomyAgentToolsNode(TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState]):
    pass


class MockTaxonomyAgentToolkit(TaxonomyAgentToolkit):
    def get_tools(self):
        return []


class ConcreteTaxonomyAgent(TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState]):
    pass


class TestTaxonomyAgent(BaseTest):
    def setUp(self):
        super().setUp()

        # Create a mock graph that will be returned by StateGraph()
        self.mock_graph = Mock()

        # Patch StateGraph in the parent class where it's actually used
        self.patcher = patch("ee.hogai.core.base.StateGraph")
        mock_state_graph_class = self.patcher.start()
        mock_state_graph_class.return_value = self.mock_graph

        self.agent = ConcreteTaxonomyAgent(
            team=self.team,
            user=self.user,
            loop_node_class=MockTaxonomyAgentNode,
            tools_node_class=MockTaxonomyAgentToolsNode,
            toolkit_class=MockTaxonomyAgentToolkit,
        )

    def tearDown(self):
        super().tearDown()
        self.patcher.stop()

    def test_agent_initialization(self):
        assert self.agent._team == self.team
        assert self.agent._user == self.user
        assert self.agent._loop_node_class == MockTaxonomyAgentNode
        assert self.agent._tools_node_class == MockTaxonomyAgentToolsNode
        assert self.agent._toolkit_class == MockTaxonomyAgentToolkit
        assert not self.agent._has_start_node

    def test_get_state_class(self):
        state_class, partial_state_class = self.agent._get_state_class(TaxonomyAgent)
        assert state_class == TaxonomyAgentState
        assert partial_state_class == TaxonomyAgentState

    def test_get_state_class_no_generic(self):
        # Create an agent without proper generic typing to test error case
        class NonGenericAgent(TaxonomyAgent):
            pass

        with pytest.raises(ValueError) as context:
            NonGenericAgent(
                team=self.team,
                user=self.user,
                loop_node_class=MockTaxonomyAgentNode,
                tools_node_class=MockTaxonomyAgentToolsNode,
                toolkit_class=MockTaxonomyAgentToolkit,
            )

        assert "Could not determine state type" in str(context.value)

    def test_add_edge(self):
        result = self.agent.add_edge(TaxonomyNodeName.START, cast(MaxNodeName, "test_node"))
        assert result == self.agent
        assert self.agent._has_start_node

    def test_add_edge_non_start(self):
        result = self.agent.add_edge(cast(MaxNodeName, "node1"), cast(MaxNodeName, "node2"))
        assert result == self.agent
        assert not self.agent._has_start_node

    def test_add_node(self):
        mock_action = Mock()
        result = self.agent.add_node(cast(MaxNodeName, "test_node"), mock_action)
        assert result == self.agent

    def test_compile_without_start_node(self):
        with pytest.raises(ValueError) as context:
            self.agent.compile()

        assert "Start node not added" in str(context.value)

    def test_compile_with_start_node(self):
        self.agent._has_start_node = True
        _ = self.agent.compile()

        # When no checkpointer is passed, it should use the global checkpointer
        self.agent._graph.compile.assert_called_once()  # type: ignore
        call_args = self.agent._graph.compile.call_args  # type: ignore
        assert call_args[1]["checkpointer"] is not None

    def test_compile_full_graph(self):
        _ = self.agent.compile_full_graph()

        # When no checkpointer is passed, it should use the global checkpointer
        self.agent._graph.compile.assert_called_once()  # type: ignore
        call_args = self.agent._graph.compile.call_args  # type: ignore
        assert call_args[1]["checkpointer"] is not None

    def test_compile_full_graph_with_checkpointer(self):
        mock_checkpointer = Mock()
        _ = self.agent.compile_full_graph(checkpointer=mock_checkpointer)

        self.agent._graph.compile.assert_called_once_with(checkpointer=mock_checkpointer)  # type: ignore

    def test_add_taxonomy_generator(self):
        _ = self.agent.add_taxonomy_generator()

        assert len(self.agent._graph.add_node.call_args_list) == 2  # type: ignore

        assert len(self.agent._graph.add_edge.call_args_list) == 2  # type: ignore

        self.agent._graph.add_conditional_edges.assert_called_once()  # type: ignore

    def test_add_taxonomy_generator_custom_next_node(self):
        custom_next = "custom_end"
        _ = self.agent.add_taxonomy_generator(next_node=cast(TaxonomyNodeName, custom_next))

        conditional_call = self.agent._graph.add_conditional_edges.call_args  # type: ignore
        assert conditional_call[0][0] == TaxonomyNodeName.TOOLS_NODE
        assert conditional_call[0][2]["end"] == custom_next

    def test_node_instantiation_in_add_taxonomy_generator(self):
        with (
            patch.object(MockTaxonomyAgentNode, "__init__", return_value=None) as mock_loop_init,
            patch.object(MockTaxonomyAgentToolsNode, "__init__", return_value=None) as mock_tools_init,
        ):
            self.agent.add_taxonomy_generator()

        mock_loop_init.assert_called_once_with(self.team, self.user, MockTaxonomyAgentToolkit)
        mock_tools_init.assert_called_once_with(self.team, self.user, MockTaxonomyAgentToolkit)
