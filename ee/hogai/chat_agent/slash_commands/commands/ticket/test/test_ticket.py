import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.utils.types import AssistantState


class TestTicketCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.command = TicketCommand(self.team, self.user)

    @pytest.mark.asyncio
    @patch.object(TicketCommand, "_summarize_conversation")
    async def test_execute_returns_summary(self, mock_summarize):
        """Test that /ticket returns the conversation summary."""
        mock_summarize.return_value = "Summary of the conversation"

        state = AssistantState(
            messages=[
                HumanMessage(content="How do I create an insight?"),
                AssistantMessage(content="You can create an insight by...", id="1"),
                HumanMessage(content="/ticket"),
            ]
        )
        config = RunnableConfig(configurable={"thread_id": "test-conversation-id", "trace_id": "test-trace-id"})

        result = await self.command.execute(config, state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertEqual(message.content, "Summary of the conversation")
        mock_summarize.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_first_message_prompts_for_input(self):
        """Test that /ticket as first message prompts user to describe issue."""
        state = AssistantState(
            messages=[
                HumanMessage(content="/ticket"),
            ]
        )
        config = RunnableConfig(configurable={"thread_id": "test-conversation-id"})

        result = await self.command.execute(config, state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("describe your issue", message.content.lower())

    def test_is_first_message_with_only_ticket_command(self):
        """Test that _is_first_message returns True when only /ticket is present."""
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        self.assertTrue(self.command._is_first_message(state))

    def test_is_first_message_with_prior_conversation(self):
        """Test that _is_first_message returns False when there's prior conversation."""
        state = AssistantState(
            messages=[
                HumanMessage(content="How do I create an insight?"),
                AssistantMessage(content="You can create an insight by...", id="1"),
                HumanMessage(content="/ticket"),
            ]
        )
        self.assertFalse(self.command._is_first_message(state))
