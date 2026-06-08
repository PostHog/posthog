from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from ee.hogai.context import AssistantContextManager

from ..ai_observability import AIObservabilityAgentToolkit


class TestAIObservabilityAgentToolkit(BaseTest):
    def test_toolkit_includes_all_tools(self):
        toolkit = AIObservabilityAgentToolkit(
            team=self.team,
            user=self.user,
            context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
        )

        tool_classes = toolkit.tools
        tool_class_names = [tool_class.__name__ for tool_class in tool_classes]

        assert "SearchLLMTracesTool" in tool_class_names
        assert "RunHogEvalTestTool" in tool_class_names
        assert "CreateLLMSkillTool" in tool_class_names
        assert "UpdateLLMSkillTool" in tool_class_names
        assert "ArchiveLLMSkillTool" in tool_class_names

    def test_toolkit_has_trajectory_examples(self):
        assert AIObservabilityAgentToolkit.POSITIVE_TODO_EXAMPLES is not None
        assert len(AIObservabilityAgentToolkit.POSITIVE_TODO_EXAMPLES or []) > 0
