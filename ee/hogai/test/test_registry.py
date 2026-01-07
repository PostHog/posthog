from posthog.test.base import BaseTest

from posthog.schema import AssistantTool


class TestToolRegistry(BaseTest):
    def test_can_get_registered_contextual_tool_class(self):
        from ee.hogai.registry import get_contextual_tool_class

        assert get_contextual_tool_class(AssistantTool.CREATE_FEATURE_FLAG) is not None

    def test_can_get_registered_contextual_tool_class_with_invalid_tool_name(self):
        from ee.hogai.registry import get_contextual_tool_class

        assert get_contextual_tool_class("invalid_tool_name") is None
