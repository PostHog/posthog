from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.feedback import FeedbackCommand
from ee.hogai.utils.types import AssistantState


class TestFeedbackCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.command = FeedbackCommand(self.team, self.user)

    def test_get_feedback_content_extracts_text(self):
        state = AssistantState(messages=[HumanMessage(content="/feedback This is great!")])
        result = self.command.get_feedback_content(state)
        self.assertEqual(result, "This is great!")

    def test_get_feedback_content_returns_none_for_empty(self):
        state = AssistantState(messages=[HumanMessage(content="/feedback")])
        result = self.command.get_feedback_content(state)
        self.assertEqual(result, "")

    def test_get_feedback_content_strips_whitespace(self):
        state = AssistantState(messages=[HumanMessage(content="/feedback   Some feedback   ")])
        result = self.command.get_feedback_content(state)
        self.assertEqual(result, "Some feedback")

    async def test_execute_returns_usage_message_when_no_text(self):
        state = AssistantState(messages=[HumanMessage(content="/feedback")])
        config: RunnableConfig = {"configurable": {"thread_id": "test-conversation-id"}}

        result = await self.command.execute(config, state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("Please provide your feedback", message.content)
        self.assertIn("/feedback <your feedback>", message.content)

    @patch("ee.hogai.chat_agent.slash_commands.commands.feedback.command.posthoganalytics.capture")
    async def test_execute_captures_feedback_event(self, mock_capture):
        state = AssistantState(messages=[HumanMessage(content="/feedback This is awesome!")])
        config: RunnableConfig = {"configurable": {"thread_id": "test-conversation-id", "trace_id": "test-trace-id"}}

        result = await self.command.execute(config, state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        self.assertEqual(message.content, "Thanks for making PostHog AI better!")

        mock_capture.assert_called_once_with(
            distinct_id=str(self.user.distinct_id),
            event="$ai_feedback",
            properties={
                "$ai_feedback_text": "This is awesome!",
                "$ai_session_id": "test-conversation-id",
                "$ai_trace_id": "test-trace-id",
            },
        )
