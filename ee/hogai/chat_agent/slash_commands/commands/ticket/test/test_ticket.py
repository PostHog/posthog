from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.utils.types import AssistantState


def _make_billing_context(subscription_level: str = "paid", trial_active: bool = False):
    return {
        "subscription_level": subscription_level,
        "has_active_subscription": subscription_level != "free",
        "products": [],
        "settings": {"autocapture_on": True, "active_destinations": 0},
        "trial": {"is_active": trial_active, "expires_at": None, "target": None} if trial_active else None,
    }


class TestTicketCommand(BaseTest):
    def setUp(self):
        super().setUp()
        # Default to old organization (more than 3 months) for consistent test behavior
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.save()
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
        config = RunnableConfig(
            configurable={
                "thread_id": "test-conversation-id",
                "trace_id": "test-trace-id",
                "billing_context": _make_billing_context("paid"),
            }
        )

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
        config = RunnableConfig(
            configurable={"thread_id": "test-conversation-id", "billing_context": _make_billing_context("paid")}
        )

        result = await self.command.execute(config, state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("describe your issue", message.content.lower())

    @pytest.mark.asyncio
    async def test_execute_free_user_returns_upgrade_message(self):
        """Test that /ticket returns upgrade message for free users."""
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(
            configurable={"thread_id": "test-conversation-id", "billing_context": _make_billing_context("free")}
        )

        result = await self.command.execute(config, state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)

    @pytest.mark.asyncio
    async def test_execute_no_billing_context_returns_upgrade_message(self):
        """Test that /ticket returns upgrade message when no billing context."""
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(configurable={"thread_id": "test-conversation-id"})

        result = await self.command.execute(config, state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)

    @pytest.mark.asyncio
    @patch.object(TicketCommand, "_summarize_conversation")
    async def test_execute_custom_subscription_allowed(self, mock_summarize):
        """Test that /ticket works for custom subscription level."""
        mock_summarize.return_value = "Summary"
        state = AssistantState(
            messages=[
                HumanMessage(content="Issue"),
                AssistantMessage(content="Response", id="1"),
                HumanMessage(content="/ticket"),
            ]
        )
        config = RunnableConfig(
            configurable={"thread_id": "test-conversation-id", "billing_context": _make_billing_context("custom")}
        )

        result = await self.command.execute(config, state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        self.assertNotIn("paid plans", message.content)

    @pytest.mark.asyncio
    async def test_execute_active_trial_allowed(self):
        """Test that /ticket works for users with active trial."""
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(
            configurable={
                "thread_id": "test-conversation-id",
                "billing_context": _make_billing_context("free", trial_active=True),
            }
        )

        result = await self.command.execute(config, state)

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

    def test_is_organization_new_returns_true_for_recent_org(self):
        """Test that _is_organization_new returns True for org created less than 3 months ago."""
        self.team.organization.created_at = timezone.now() - timedelta(days=30)
        self.team.organization.save()
        self.assertTrue(self.command._is_organization_new())

    def test_is_organization_new_returns_false_for_old_org(self):
        """Test that _is_organization_new returns False for org created more than 3 months ago."""
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.save()
        self.assertFalse(self.command._is_organization_new())

    @pytest.mark.asyncio
    @patch.object(TicketCommand, "_is_organization_new", return_value=True)
    async def test_execute_new_org_free_user_allowed(self, mock_is_new):
        """Test that /ticket works for free users in new organizations."""
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(
            configurable={"thread_id": "test-conversation-id", "billing_context": _make_billing_context("free")}
        )

        result = await self.command.execute(config, state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("describe your issue", message.content.lower())

    @pytest.mark.asyncio
    @patch.object(TicketCommand, "_is_organization_new", return_value=False)
    async def test_execute_old_org_free_user_blocked(self, mock_is_new):
        """Test that /ticket returns upgrade message for free users in old organizations."""
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(
            configurable={"thread_id": "test-conversation-id", "billing_context": _make_billing_context("free")}
        )

        result = await self.command.execute(config, state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)
