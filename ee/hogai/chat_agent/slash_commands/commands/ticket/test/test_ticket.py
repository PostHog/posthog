from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AssistantMessage,
    HumanMessage,
    MaxBillingContext,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxBillingContextTrial,
)

from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.utils.types import AssistantState


def _make_server_billing_context(subscription_level: str = "paid", trial_active: bool = False) -> MaxBillingContext:
    return MaxBillingContext(
        subscription_level=MaxBillingContextSubscriptionLevel(subscription_level),
        has_active_subscription=subscription_level != "free",
        products=[],
        settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=0),
        trial=MaxBillingContextTrial(is_active=trial_active, expires_at=None, target=None) if trial_active else None,
    )


class TestTicketCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.save()
        self.command = TicketCommand(self.team, self.user)

    @pytest.mark.asyncio
    @patch(
        "ee.hogai.chat_agent.slash_commands.commands.ticket.command.fetch_server_billing_context",
    )
    @patch.object(TicketCommand, "_summarize_conversation")
    async def test_execute_returns_summary(self, mock_summarize, mock_fetch_billing):
        mock_fetch_billing.return_value = _make_server_billing_context("paid")
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
    @patch(
        "ee.hogai.chat_agent.slash_commands.commands.ticket.command.fetch_server_billing_context",
    )
    async def test_execute_first_message_prompts_for_input(self, mock_fetch_billing):
        mock_fetch_billing.return_value = _make_server_billing_context("paid")
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

    @pytest.mark.asyncio
    @patch(
        "ee.hogai.chat_agent.slash_commands.commands.ticket.command.fetch_server_billing_context",
    )
    async def test_execute_free_user_returns_upgrade_message(self, mock_fetch_billing):
        mock_fetch_billing.return_value = _make_server_billing_context("free")
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(configurable={"thread_id": "test-conversation-id"})

        result = await self.command.execute(config, state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)

    @pytest.mark.asyncio
    @patch(
        "ee.hogai.chat_agent.slash_commands.commands.ticket.command.fetch_server_billing_context",
    )
    async def test_execute_billing_unavailable_returns_upgrade_message(self, mock_fetch_billing):
        mock_fetch_billing.return_value = None
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(configurable={"thread_id": "test-conversation-id"})

        result = await self.command.execute(config, state)

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)

    @pytest.mark.asyncio
    @patch(
        "ee.hogai.chat_agent.slash_commands.commands.ticket.command.fetch_server_billing_context",
    )
    @patch.object(TicketCommand, "_summarize_conversation")
    async def test_execute_custom_subscription_allowed(self, mock_summarize, mock_fetch_billing):
        mock_fetch_billing.return_value = _make_server_billing_context("custom")
        mock_summarize.return_value = "Summary"
        state = AssistantState(
            messages=[
                HumanMessage(content="Issue"),
                AssistantMessage(content="Response", id="1"),
                HumanMessage(content="/ticket"),
            ]
        )
        config = RunnableConfig(configurable={"thread_id": "test-conversation-id"})

        result = await self.command.execute(config, state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        self.assertNotIn("paid plans", message.content)

    @pytest.mark.asyncio
    @patch(
        "ee.hogai.chat_agent.slash_commands.commands.ticket.command.fetch_server_billing_context",
    )
    async def test_execute_active_trial_allowed(self, mock_fetch_billing):
        mock_fetch_billing.return_value = _make_server_billing_context("free", trial_active=True)
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(configurable={"thread_id": "test-conversation-id"})

        result = await self.command.execute(config, state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("describe your issue", message.content.lower())

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

    @pytest.mark.asyncio
    @patch.object(TicketCommand, "_is_organization_new", return_value=True)
    async def test_execute_new_org_free_user_allowed(self, mock_is_new):
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(configurable={"thread_id": "test-conversation-id"})

        result = await self.command.execute(config, state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("describe your issue", message.content.lower())

    @pytest.mark.asyncio
    @patch(
        "ee.hogai.chat_agent.slash_commands.commands.ticket.command.fetch_server_billing_context",
    )
    @patch.object(TicketCommand, "_is_organization_new", return_value=False)
    async def test_execute_old_org_free_user_blocked(self, mock_is_new, mock_fetch_billing):
        mock_fetch_billing.return_value = _make_server_billing_context("free")
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        config = RunnableConfig(configurable={"thread_id": "test-conversation-id"})

        result = await self.command.execute(config, state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn("paid plans", message.content)
