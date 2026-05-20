from unittest import TestCase

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
        assert UserInterviewAgentToolkit.POSITIVE_TODO_EXAMPLES is not None
        self.assertGreater(len(UserInterviewAgentToolkit.POSITIVE_TODO_EXAMPLES), 0)

    def test_mode_definitions_use_correct_mode(self):
        self.assertEqual(user_interview_agent.mode, AgentMode.USER_INTERVIEW)
        self.assertEqual(subagent_user_interview_agent.mode, AgentMode.USER_INTERVIEW)
        self.assertEqual(chat_agent_plan_user_interview_agent.mode, AgentMode.USER_INTERVIEW)

    def test_subagent_uses_read_only_toolkit(self):
        self.assertEqual(subagent_user_interview_agent.toolkit_class, ReadOnlyUserInterviewAgentToolkit)
        self.assertEqual(chat_agent_plan_user_interview_agent.toolkit_class, ReadOnlyUserInterviewAgentToolkit)
