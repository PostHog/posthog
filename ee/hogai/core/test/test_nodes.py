from posthog.test.base import BaseTest

from ee.hogai.core.context import set_node_path
from ee.hogai.core.node import AssistantNode
from ee.hogai.utils.types.base import NodePath


class TestNodePath(BaseTest):
    def test_node_path_property_with_explicit_path_doesnt_append(self):
        """When node_path is explicitly set, it should return it as-is without appending node name"""
        custom_path = (NodePath(name="custom_graph"), NodePath(name="custom_node"))

        class TestNode(AssistantNode):
            def run(self, state, config):
                return None

        node = TestNode(self.team, self.user, node_path=custom_path)

        # When path is explicitly set, it should be returned as-is without appending the node name
        result_path = node.node_path
        assert len(result_path) == 2
        assert result_path[0].name == "custom_graph"
        assert result_path[1].name == "custom_node"
        # Should NOT have "TestNode" appended
        assert not node._is_context_path_used

    def test_node_path_property_with_none_uses_context_and_appends(self):
        """When node_path is None, it should use path from context and append node name"""
        context_path = (NodePath(name="context_graph"),)

        class TestNode(AssistantNode):
            def run(self, state, config):
                return None

        # Initialize node within a context
        with set_node_path(context_path):
            node = TestNode(self.team, self.user, node_path=None)

        # When path is None, it should use context path and append node name
        result_path = node.node_path
        assert len(result_path) == 2
        assert result_path[0].name == "context_graph"
        assert result_path[1].name == "TestNode"
        assert node._is_context_path_used

    def test_node_path_property_with_none_and_empty_context_appends(self):
        """When node_path is None and context is empty, it should use empty tuple and append node name"""

        class TestNode(AssistantNode):
            def run(self, state, config):
                return None

        # Initialize node without any context
        node = TestNode(self.team, self.user, node_path=None)

        # When both path and context are None, it should use empty tuple and append node name
        result_path = node.node_path
        assert len(result_path) == 1
        assert result_path[0].name == "TestNode"
        assert node._is_context_path_used
