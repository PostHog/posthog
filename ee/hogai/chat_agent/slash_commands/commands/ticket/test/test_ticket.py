from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.utils.types import AssistantState

COMMAND_MODULE = "ee.hogai.chat_agent.slash_commands.commands.ticket.command"

UPGRADE_MARKER = "paid plans"
DESCRIBE_ISSUE_MARKER = "describe your issue"


class TestTicketCommand(BaseTest):
    def setUp(self):
        super().setUp()
        # Old organization by default, so eligibility is decided by billing rather than the new-org grace period
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.save()
        self.command = TicketCommand(self.team, self.user)

    def _config(self) -> RunnableConfig:
        return RunnableConfig(configurable={"thread_id": "test-conversation-id"})

    async def _execute_with_billing(
        self, billing_response: dict | Exception, state: AssistantState | None = None
    ) -> AssistantMessage:
        state = state or AssistantState(messages=[HumanMessage(content="/ticket")])
        with (
            patch(f"{COMMAND_MODULE}.get_cached_instance_license", return_value=MagicMock()),
            patch(f"{COMMAND_MODULE}.BillingManager") as mock_manager,
        ):
            if isinstance(billing_response, Exception):
                mock_manager.return_value._get_billing.side_effect = billing_response
            else:
                mock_manager.return_value._get_billing.return_value = billing_response
            result = await self.command.execute(self._config(), state)
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        return message

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

        message = await self._execute_with_billing({"customer": {"subscription_level": "paid"}}, state=state)

        self.assertEqual(message.content, "Summary of the conversation")
        mock_summarize.assert_called_once()

    async def test_execute_first_message_prompts_for_input(self):
        message = await self._execute_with_billing({"customer": {"subscription_level": "paid"}})

        self.assertIn(DESCRIBE_ISSUE_MARKER, message.content.lower())

    @parameterized.expand(
        [
            ("paid_subscription", {"customer": {"subscription_level": "paid"}}, True),
            ("custom_subscription", {"customer": {"subscription_level": "custom"}}, True),
            ("active_trial", {"customer": {"subscription_level": "free", "trial": {"status": "active"}}}, True),
            ("free_plan", {"customer": {"subscription_level": "free"}}, False),
            ("expired_trial", {"customer": {"subscription_level": "free", "trial": {"status": "expired"}}}, False),
            ("no_customer_info", {}, False),
        ]
    )
    async def test_eligibility_follows_billing_subscription(self, _name, billing_response, allowed):
        message = await self._execute_with_billing(billing_response)

        if allowed:
            self.assertIn(DESCRIBE_ISSUE_MARKER, message.content.lower())
        else:
            self.assertIn(UPGRADE_MARKER, message.content)

    async def test_billing_error_fails_closed(self):
        message = await self._execute_with_billing(Exception("billing service unavailable"))

        self.assertIn(UPGRADE_MARKER, message.content)

    async def test_no_license_denied_without_billing_call(self):
        state = AssistantState(messages=[HumanMessage(content="/ticket")])
        with (
            patch(f"{COMMAND_MODULE}.get_cached_instance_license", return_value=None),
            patch(f"{COMMAND_MODULE}.BillingManager") as mock_manager,
        ):
            result = await self.command.execute(self._config(), state)

        mock_manager.assert_not_called()
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        self.assertIn(UPGRADE_MARKER, message.content)

    async def test_new_org_allowed_without_billing_check(self):
        self.team.organization.created_at = timezone.now() - timedelta(days=30)
        await sync_to_async(self.team.organization.save)()
        state = AssistantState(messages=[HumanMessage(content="/ticket")])

        with patch(f"{COMMAND_MODULE}.BillingManager") as mock_manager:
            result = await self.command.execute(self._config(), state)

        mock_manager.assert_not_called()
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

    async def test_is_organization_new_returns_true_for_recent_org(self):
        self.team.organization.created_at = timezone.now() - timedelta(days=30)
        await sync_to_async(self.team.organization.save)()
        self.assertTrue(await self.command._is_organization_new())

    async def test_is_organization_new_returns_false_for_old_org(self):
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        await sync_to_async(self.team.organization.save)()
        self.assertFalse(await self.command._is_organization_new())
