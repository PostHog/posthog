from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from langgraph.types import Send

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.chat_agent.slash_commands.commands.feedback import FeedbackCommand
from ee.hogai.chat_agent.slash_commands.commands.remember import RememberCommand
from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.chat_agent.slash_commands.commands.usage import UsageCommand
from ee.hogai.chat_agent.slash_commands.nodes import SlashCommandHandlerNode
from ee.hogai.core.agent_modes.const import SlashCommandName
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantNodeName


class TestSlashCommandHandlerNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.node = SlashCommandHandlerNode(self.team, self.user)

    def test_get_command_detects_usage(self):
        """Test that /usage command is detected."""
        state = AssistantState(messages=[HumanMessage(content="/usage")])
        result = self.node._get_command(state)
        self.assertEqual(result, SlashCommandName.FIELD_USAGE)

    def test_get_command_detects_usage_with_whitespace(self):
        """Test that /usage command with trailing whitespace is detected."""
        state = AssistantState(messages=[HumanMessage(content="/usage  ")])
        result = self.node._get_command(state)
        self.assertEqual(result, SlashCommandName.FIELD_USAGE)

    def test_get_command_returns_none_for_non_command(self):
        """Test that non-command messages return None."""
        state = AssistantState(messages=[HumanMessage(content="Hello, how are you?")])
        result = self.node._get_command(state)
        self.assertIsNone(result)

    def test_get_command_returns_none_for_empty_messages(self):
        """Test that empty messages return None."""
        state = AssistantState(messages=[])
        result = self.node._get_command(state)
        self.assertIsNone(result)

    def test_get_command_ignores_assistant_messages(self):
        """Test that assistant messages don't trigger command detection."""
        state = AssistantState(messages=[AssistantMessage(content="/usage", id="123")])
        result = self.node._get_command(state)
        self.assertIsNone(result)

    async def test_router_returns_end_for_command(self):
        """Test that commands route to END (handled in arun)."""
        state = AssistantState(messages=[HumanMessage(content="/usage")])
        result = await self.node.arouter(state)
        self.assertEqual(result, AssistantNodeName.END)

    async def test_router_returns_send_list_for_non_command(self):
        """Test that non-command messages route to normal flow."""
        state = AssistantState(messages=[HumanMessage(content="Hello, how are you?")])
        with patch.object(self.node, "_team", self.team), patch.object(self.node, "_user", self.user):
            result = await self.node.arouter(state)

        self.assertIsInstance(result, list)
        send_list = cast(list[Send], result)
        self.assertEqual(len(send_list), 2)
        self.assertIsInstance(send_list[0], Send)
        self.assertIsInstance(send_list[1], Send)
        self.assertEqual(send_list[0].node, AssistantNodeName.ROOT)
        self.assertEqual(send_list[1].node, AssistantNodeName.MEMORY_COLLECTOR)

    async def test_router_returns_send_list_for_empty_messages(self):
        """Test that empty messages route to normal flow."""
        state = AssistantState(messages=[])
        with patch.object(self.node, "_team", self.team), patch.object(self.node, "_user", self.user):
            result = await self.node.arouter(state)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_command_handlers_contains_usage(self):
        """Test that COMMAND_HANDLERS registry contains /usage with correct class."""
        self.assertIn(SlashCommandName.FIELD_USAGE, SlashCommandHandlerNode.COMMAND_HANDLERS)
        self.assertEqual(
            SlashCommandHandlerNode.COMMAND_HANDLERS[SlashCommandName.FIELD_USAGE],
            UsageCommand,
        )

    def test_command_handlers_contains_remember(self):
        """Test that COMMAND_HANDLERS registry contains /remember with correct class."""
        self.assertIn(SlashCommandName.FIELD_REMEMBER, SlashCommandHandlerNode.COMMAND_HANDLERS)
        self.assertEqual(
            SlashCommandHandlerNode.COMMAND_HANDLERS[SlashCommandName.FIELD_REMEMBER],
            RememberCommand,
        )

    def test_command_handlers_are_slash_command_subclasses(self):
        """Test that all handlers are SlashCommand subclasses."""
        for command_class in SlashCommandHandlerNode.COMMAND_HANDLERS.values():
            self.assertTrue(issubclass(command_class, SlashCommand))

    def test_get_command_detects_remember(self):
        """Test that /remember command without args is detected."""
        state = AssistantState(messages=[HumanMessage(content="/remember")])
        result = self.node._get_command(state)
        self.assertEqual(result, SlashCommandName.FIELD_REMEMBER)

    def test_get_command_detects_remember_with_args(self):
        """Test that /remember command with args is detected."""
        state = AssistantState(messages=[HumanMessage(content="/remember My main KPI is MAU")])
        result = self.node._get_command(state)
        self.assertEqual(result, SlashCommandName.FIELD_REMEMBER)

    async def test_router_returns_end_for_remember_command(self):
        """Test that /remember command routes to END."""
        state = AssistantState(messages=[HumanMessage(content="/remember test fact")])
        result = await self.node.arouter(state)
        self.assertEqual(result, AssistantNodeName.END)

    def test_command_handlers_contains_feedback(self):
        """Test that COMMAND_HANDLERS registry contains /feedback with correct class."""
        self.assertIn(SlashCommandName.FIELD_FEEDBACK, SlashCommandHandlerNode.COMMAND_HANDLERS)
        self.assertEqual(
            SlashCommandHandlerNode.COMMAND_HANDLERS[SlashCommandName.FIELD_FEEDBACK],
            FeedbackCommand,
        )

    def test_get_command_detects_feedback(self):
        """Test that /feedback command is detected."""
        state = AssistantState(messages=[HumanMessage(content="/feedback")])
        result = self.node._get_command(state)
        self.assertEqual(result, SlashCommandName.FIELD_FEEDBACK)

    async def test_router_returns_end_for_feedback_command(self):
        """Test that /feedback command routes to END."""
        state = AssistantState(messages=[HumanMessage(content="/feedback")])
        result = await self.node.arouter(state)
        self.assertEqual(result, AssistantNodeName.END)

    def test_get_command_detects_feedback_with_args(self):
        """Test that /feedback command with args is detected."""
        state = AssistantState(messages=[HumanMessage(content="/feedback This is great!")])
        result = self.node._get_command(state)
        self.assertEqual(result, SlashCommandName.FIELD_FEEDBACK)

    def test_command_handlers_contains_ticket(self):
        """Test that COMMAND_HANDLERS registry contains /ticket with correct class."""
        self.assertIn(SlashCommandName.FIELD_TICKET, SlashCommandHandlerNode.COMMAND_HANDLERS)
        self.assertEqual(
            SlashCommandHandlerNode.COMMAND_HANDLERS[SlashCommandName.FIELD_TICKET],
            TicketCommand,
        )

    def test_get_command_detects_ticket(self):
        """Test that /ticket command is detected."""
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        result = self.node._get_command(state)
        self.assertEqual(result, SlashCommandName.FIELD_TICKET)

    async def test_router_returns_end_for_ticket_command(self):
        """Test that /ticket command routes to END."""
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        result = await self.node.arouter(state)
        self.assertEqual(result, AssistantNodeName.END)
