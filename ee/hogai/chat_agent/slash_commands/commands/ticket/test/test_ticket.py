from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.utils.types import AssistantState

DESCRIBE_ISSUE_MARKER = "describe your issue"


class TestTicketCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.command = TicketCommand(self.team, self.user)

    def _config(self) -> RunnableConfig:
        return RunnableConfig(configurable={"thread_id": "test-conversation-id"})

    @patch.object(TicketCommand, "_summarize_conversation")
    async def test_execute_returns_summary(self, mock_summarize):
        mock_summarize.return_value = "Summary of the conversation"
        state = AssistantState(
            messages=[
                HumanMessage(content="How do I create an insight?"),
                AssistantMessage(content="You can create an insight by...", id="1"),
                HumanMessage(content="/ticket"),
            ]
        )

        result = await self.command.execute(self._config(), state)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        self.assertEqual(message.content, "Summary of the conversation")
        mock_summarize.assert_called_once()

    async def test_execute_first_message_prompts_for_input(self):
        state = AssistantState(messages=[HumanMessage(content="/ticket")])

        result = await self.command.execute(self._config(), state)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn(DESCRIBE_ISSUE_MARKER, message.content.lower())

    def test_is_first_message_with_only_ticket_command(self):
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        self.assertTrue(self.command._is_first_message(state))

    def test_is_first_message_with_prior_conversation(self):
        state = AssistantState(
            messages=[
                HumanMessage(content="How do I create an insight?"),
                AssistantMessage(content="You can create an insight by...", id="1"),
                HumanMessage(content="/ticket"),
            ]
        )
        self.assertFalse(self.command._is_first_message(state))
