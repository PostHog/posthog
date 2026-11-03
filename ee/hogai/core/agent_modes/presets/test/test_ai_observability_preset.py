from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from ee.hogai.context import AssistantContextManager

from ..ai_observability import AIObservabilityAgentToolkit


class TestAIObservabilityAgentToolkit(BaseTest):
    @parameterized.expand([("flag_on", True), ("flag_off", False)])
    def test_toolkit_includes_all_tools(self, _name: str, suggest_evals_enabled: bool):
        with patch(
            "ee.hogai.core.agent_modes.presets.ai_observability.has_suggest_evals_feature_flag",
            return_value=suggest_evals_enabled,
        ):
            tool_class_names = [tool_class.__name__ for tool_class in self._toolkit().tools]

        self.assertIn("SearchLLMTracesTool", tool_class_names)
        self.assertIn("RunHogEvalTestTool", tool_class_names)
        self.assertIn("CreateLLMSkillTool", tool_class_names)
        self.assertIn("UpdateLLMSkillTool", tool_class_names)
        self.assertIn("ArchiveLLMSkillTool", tool_class_names)
        self.assertEqual("CreateEvaluationTool" in tool_class_names, suggest_evals_enabled)

    def _toolkit(self) -> AIObservabilityAgentToolkit:
        return AIObservabilityAgentToolkit(
            team=self.team,
            user=self.user,
            context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
        )

    def test_toolkit_has_trajectory_examples(self):
        self.assertIsNotNone(AIObservabilityAgentToolkit.POSITIVE_TODO_EXAMPLES)
        self.assertGreater(len(AIObservabilityAgentToolkit.POSITIVE_TODO_EXAMPLES or []), 0)
