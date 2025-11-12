from posthog.test.base import BaseTest

from posthog.schema import AssistantTool


class TestToolRegistry(BaseTest):
    def test_can_get_registered_contextual_tool_class(self):
        from ee.hogai.registry import get_contextual_tool_class

        self.assertIsNotNone(get_contextual_tool_class(AssistantTool.GENERATE_HOGQL_QUERY))
