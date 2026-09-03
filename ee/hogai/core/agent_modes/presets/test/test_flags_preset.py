from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from ee.hogai.context import AssistantContextManager

from ..flags import FlagsAgentToolkit, ReadOnlyFlagsAgentToolkit


class TestFlagsAgentToolkit(BaseTest):
    @patch("ee.hogai.core.agent_modes.presets.flags.has_experiment_summary_tool_feature_flag", return_value=True)
    def test_toolkit_includes_all_tools(self, _mock_flag):
        toolkit = FlagsAgentToolkit(
            team=self.team,
            user=self.user,
            context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
        )

        tool_classes = toolkit.tools
        tool_class_names = [tool_class.__name__ for tool_class in tool_classes]

        self.assertIn("CreateFeatureFlagTool", tool_class_names)
        self.assertIn("CreateExperimentTool", tool_class_names)
        self.assertIn("ExperimentSummaryTool", tool_class_names)

    def test_toolkit_has_trajectory_examples(self):
        self.assertIsNotNone(FlagsAgentToolkit.POSITIVE_TODO_EXAMPLES)
        self.assertGreater(len(FlagsAgentToolkit.POSITIVE_TODO_EXAMPLES), 0)


class TestReadOnlyFlagsAgentToolkit(BaseTest):
    # The readonly toolkit is the whole custom toolset for the plan-only flags mode, and the
    # experiment summary flag is the only thing that varies it. Asserting the exact list, rather
    # than membership, keeps a writing tool from being added here unnoticed.
    @parameterized.expand(
        [
            ("flag_enabled", True, ["ExperimentSummaryTool"]),
            ("flag_disabled", False, []),
        ]
    )
    def test_tools_follow_experiment_summary_flag(self, _name, flag_enabled, expected_tool_names):
        with patch(
            "ee.hogai.core.agent_modes.presets.flags.has_experiment_summary_tool_feature_flag",
            return_value=flag_enabled,
        ):
            toolkit = ReadOnlyFlagsAgentToolkit(
                team=self.team,
                user=self.user,
                context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
            )

            self.assertEqual([tool_class.__name__ for tool_class in toolkit.tools], expected_tool_names)
