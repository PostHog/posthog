from unittest import TestCase

from parameterized import parameterized

from posthog.schema import AgentMode

from ..user_interview import (
    ReadOnlyUserInterviewAgentToolkit,
    UserInterviewAgentToolkit,
    chat_agent_plan_user_interview_agent,
    subagent_user_interview_agent,
    user_interview_agent,
)


class TestUserInterviewAgentToolkit(TestCase):
    def test_toolkit_includes_both_user_interview_tools(self):
        # The `tools` property only imports and returns classes — it does not touch instance state,
        # so we can resolve it via the descriptor without constructing a full toolkit.
        tool_classes = UserInterviewAgentToolkit.tools.fget(None)  # type: ignore[union-attr]
        tool_class_names = [tool_class.__name__ for tool_class in tool_classes]

        self.assertIn("CreateUserInterviewTopicTool", tool_class_names)
        self.assertIn("AnalyzeUserInterviewsTool", tool_class_names)

    def test_read_only_toolkit_excludes_create_tool(self):
        tool_classes = ReadOnlyUserInterviewAgentToolkit.tools.fget(None)  # type: ignore[union-attr]
        tool_class_names = [tool_class.__name__ for tool_class in tool_classes]

        self.assertEqual(tool_class_names, ["AnalyzeUserInterviewsTool"])

    def test_toolkit_has_trajectory_examples(self):
        self.assertIsNotNone(UserInterviewAgentToolkit.POSITIVE_TODO_EXAMPLES)
        self.assertGreater(len(UserInterviewAgentToolkit.POSITIVE_TODO_EXAMPLES), 0)  # type: ignore[arg-type]

    @parameterized.expand(
        [
            ("user_interview_agent", user_interview_agent),
            ("subagent_user_interview_agent", subagent_user_interview_agent),
            ("chat_agent_plan_user_interview_agent", chat_agent_plan_user_interview_agent),
        ]
    )
    def test_mode_definition_uses_user_interview_mode(self, _name, definition):
        self.assertEqual(definition.mode, AgentMode.USER_INTERVIEW)

    @parameterized.expand(
        [
            ("subagent_user_interview_agent", subagent_user_interview_agent),
            ("chat_agent_plan_user_interview_agent", chat_agent_plan_user_interview_agent),
        ]
    )
    def test_read_only_variants_use_read_only_toolkit(self, _name, definition):
        self.assertEqual(definition.toolkit_class, ReadOnlyUserInterviewAgentToolkit)
