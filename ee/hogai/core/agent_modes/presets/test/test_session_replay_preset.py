from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from ee.hogai.context import AssistantContextManager

from ..session_replay import SessionReplayAgentToolkit


class TestSessionReplayAgentToolkit(BaseTest):
    def test_toolkit_includes_all_tools(self):
        toolkit = SessionReplayAgentToolkit(
            team=self.team,
            user=self.user,
            context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
        )

        tool_class_names = [tool_class.__name__ for tool_class in toolkit.tools]

        self.assertIn("FilterSessionRecordingsTool", tool_class_names)
        self.assertIn("SummarizeSessionsTool", tool_class_names)
        self.assertIn("DiagnoseMissingRecordingsTool", tool_class_names)

    def test_toolkit_has_trajectory_examples(self):
        self.assertIsNotNone(SessionReplayAgentToolkit.POSITIVE_TODO_EXAMPLES)
        self.assertGreater(len(SessionReplayAgentToolkit.POSITIVE_TODO_EXAMPLES or []), 0)

    def test_toolkit_includes_diagnose_missing_recordings_example(self):
        examples = SessionReplayAgentToolkit.POSITIVE_TODO_EXAMPLES or []
        self.assertTrue(
            any("diagnose_missing_recordings" in ex.example for ex in examples),
            "expected at least one positive todo example referencing diagnose_missing_recordings",
        )
