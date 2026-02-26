from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.utils.types import AssistantState


def _make_config(**extra_configurable):
    return RunnableConfig(configurable={"thread_id": "test-conversation-id", **extra_configurable})


def _mock_billing_response(has_active_subscription: bool = True) -> dict:
    return {"has_active_subscription": has_active_subscription, "products": []}


class TestTicketCommandPaidOrg(BaseTest):
    """Tests for /ticket with a paid organization (has active subscription)."""

    def setUp(self):
        super().setUp()
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.customer_id = "cus_test123"
        self.team.organization.save()
        self.command = TicketCommand(self.team, self.user)

    @pytest.mark.asyncio
    @patch.object(TicketCommand, "_summarize_conversation")
    @patch("ee.hogai.chat_agent.slash_commands.commands.ticket.command.BillingManager")
    async def test_execute_returns_summary(self, MockBillingManager, mock_summarize):
        MockBillingManager.return_value.get_billing.return_value = _mock_billing_response()
        mock_summarize.return_value = "Summary of the conversation"

        state = AssistantState(
            messages=[
                HumanMessage(content="How do I create an insight?"),
                AssistantMessage(content="You can create an insight by...", id="1"),
                HumanMessage(content="/ticket"),
            ]
        )

        result = await self.command.execute(_make_config(), state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertEqual(message.content, "Summary of the conversation")
        mock_summarize.assert_called_once()

    @pytest.mark.asyncio
    @patch("ee.hogai.chat_agent.slash_commands.commands.ticket.command.BillingManager")
    async def test_execute_first_message_prompts_for_input(self, MockBillingManager):
        MockBillingManager.return_value.get_billing.return_value = _mock_billing_response()

        state = AssistantState(messages=[HumanMessage(content="/ticket")])

        result = await self.command.execute(_make_config(), state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("describe your issue", message.content.lower())

    @pytest.mark.asyncio
    @patch.object(TicketCommand, "_summarize_conversation")
    @patch("ee.hogai.chat_agent.slash_commands.commands.ticket.command.BillingManager")
    async def test_execute_active_subscription_allowed(self, MockBillingManager, mock_summarize):
        MockBillingManager.return_value.get_billing.return_value = _mock_billing_response(has_active_subscription=True)
        mock_summarize.return_value = "Summary"

        state = AssistantState(
            messages=[
                HumanMessage(content="Issue"),
                AssistantMessage(content="Response", id="1"),
                HumanMessage(content="/ticket"),
            ]
        )

        result = await self.command.execute(_make_config(), state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        self.assertNotIn("paid plans", message.content)


class TestTicketCommandFreeOrg(BaseTest):
    """Tests for /ticket with a free organization."""

    def setUp(self):
        super().setUp()
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.customer_id = None
        self.team.organization.save()
        self.command = TicketCommand(self.team, self.user)

    @pytest.mark.asyncio
    async def test_execute_no_customer_id_returns_upgrade_message(self):
        state = AssistantState(messages=[HumanMessage(content="/ticket")])

        result = await self.command.execute(_make_config(), state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)

    @pytest.mark.asyncio
    async def test_execute_spoofed_billing_context_blocked(self):
        """Verify that client-supplied billing_context cannot bypass the authorization check."""
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = _make_config(
            billing_context={
                "subscription_level": "paid",
                "has_active_subscription": True,
                "products": [],
                "settings": {"autocapture_on": True, "active_destinations": 0},
            }
        )

        result = await self.command.execute(config, state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)


class TestTicketCommandInactiveSubscription(BaseTest):
    """Tests for /ticket with customer_id but inactive subscription."""

    def setUp(self):
        super().setUp()
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.customer_id = "cus_cancelled123"
        self.team.organization.save()
        self.command = TicketCommand(self.team, self.user)

    @pytest.mark.asyncio
    @patch("ee.hogai.chat_agent.slash_commands.commands.ticket.command.BillingManager")
    async def test_execute_inactive_subscription_blocked(self, MockBillingManager):
        MockBillingManager.return_value.get_billing.return_value = _mock_billing_response(has_active_subscription=False)

        state = AssistantState(messages=[HumanMessage(content="/ticket")])

        result = await self.command.execute(_make_config(), state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)

    @pytest.mark.asyncio
    @patch("ee.hogai.chat_agent.slash_commands.commands.ticket.command.BillingManager")
    async def test_execute_billing_service_error_blocks(self, MockBillingManager):
        MockBillingManager.return_value.get_billing.side_effect = Exception("billing service down")

        state = AssistantState(messages=[HumanMessage(content="/ticket")])

        result = await self.command.execute(_make_config(), state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)


class TestTicketCommandNewOrg(BaseTest):
    """Tests for /ticket with a new organization (< 3 months, always allowed)."""

    def setUp(self):
        super().setUp()
        self.team.organization.created_at = timezone.now() - timedelta(days=30)
        self.team.organization.customer_id = None
        self.team.organization.save()
        self.command = TicketCommand(self.team, self.user)

    @pytest.mark.asyncio
    async def test_execute_new_org_free_user_allowed(self):
        state = AssistantState(messages=[HumanMessage(content="/ticket")])

        result = await self.command.execute(_make_config(), state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("describe your issue", message.content.lower())


class TestTicketCommandHelpers(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.save()
        self.command = TicketCommand(self.team, self.user)

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

    def test_is_organization_new_returns_true_for_recent_org(self):
        self.team.organization.created_at = timezone.now() - timedelta(days=30)
        self.team.organization.save()
        self.assertTrue(self.command._is_organization_new())

    def test_is_organization_new_returns_false_for_old_org(self):
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.save()
        self.assertFalse(self.command._is_organization_new())
