from posthog.test.base import BaseTest

from pydantic import BaseModel

from ee.hogai.graph.base.context import set_node_path
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import NodePath


class DummyToolInput(BaseModel):
    input_value: str


class TestNodePathTool(MaxTool):
    name: str = "read_taxonomy"
    description: str = "A test tool for node_path testing"
    args_schema: type[BaseModel] = DummyToolInput

    async def _arun_impl(self, input_value: str):
        return ("result", {})


class TestMaxToolNodePath(BaseTest):
    def test_node_path_uses_context_when_not_passed(self):
        context_path = (
            NodePath(name="parent_node"),
            NodePath(name="child_node"),
        )

        with set_node_path(context_path):
            tool = TestNodePathTool(team=self.team, user=self.user)

            result = tool.node_path

            self.assertEqual(len(result), 3)
            self.assertEqual(result[0].name, "parent_node")
            self.assertEqual(result[1].name, "child_node")
            self.assertEqual(result[2].name, "max_tool.read_taxonomy")

    def test_node_path_uses_empty_tuple_when_no_context(self):
        tool = TestNodePathTool(team=self.team, user=self.user, node_path=None)

        result = tool.node_path

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "max_tool.read_taxonomy")

    def test_node_path_uses_provided_path(self):
        provided_path = (
            NodePath(name="explicit_parent"),
            NodePath(name="explicit_child"),
        )

        tool = TestNodePathTool(team=self.team, user=self.user, node_path=provided_path)

        result = tool.node_path

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].name, "explicit_parent")
        self.assertEqual(result[1].name, "explicit_child")
        self.assertEqual(result[2].name, "max_tool.read_taxonomy")
