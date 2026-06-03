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

        self.assertIn("SearchLLMTracesTool", tool_class_names)
        self.assertIn("RunHogEvalTestTool", tool_class_names)
        self.assertIn("CreateLLMSkillTool", tool_class_names)
        self.assertIn("UpdateLLMSkillTool", tool_class_names)
        self.assertIn("ArchiveLLMSkillTool", tool_class_names)

    def test_toolkit_has_trajectory_examples(self):
        self.assertIsNotNone(AIObservabilityAgentToolkit.POSITIVE_TODO_EXAMPLES)
        self.assertGreater(len(AIObservabilityAgentToolkit.POSITIVE_TODO_EXAMPLES or []), 0)
