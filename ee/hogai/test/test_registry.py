from posthog.test.base import BaseTest

from posthog.schema import AssistantTool

from products.data_warehouse.backend.max_tools import HogQLGeneratorTool

from ee.hogai.registry import get_contextual_tool_class


class TestToolRegistry(BaseTest):
    def test_can_get_registered_contextual_tool_class(self):
        self.assertEqual(get_contextual_tool_class(AssistantTool.GENERATE_HOGQL_QUERY), HogQLGeneratorTool)
