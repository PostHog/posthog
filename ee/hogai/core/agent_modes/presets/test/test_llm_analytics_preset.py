from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from ee.hogai.context import AssistantContextManager

from ..llm_analytics import LLMAnalyticsAgentToolkit


class TestLLMAnalyticsAgentToolkit(BaseTest):
    def test_toolkit_includes_all_tools(self):
        toolkit = LLMAnalyticsAgentToolkit(
            team=self.team,
            user=self.user,
            context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
        )

        tool_classes = toolkit.tools
        tool_class_names = [tool_class.__name__ for tool_class in tool_classes]

        assert "SearchLLMTracesTool" in tool_class_names

    def test_toolkit_has_trajectory_examples(self):
        assert LLMAnalyticsAgentToolkit.POSITIVE_TODO_EXAMPLES is not None
        assert len(LLMAnalyticsAgentToolkit.POSITIVE_TODO_EXAMPLES or []) > 0
