from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.utils.types import AssistantState

UPGRADE_MARKER = "paid plans"
DESCRIBE_ISSUE_MARKER = "describe your issue"

PAID_FEATURES = [{"key": "alerts", "name": "Alerts"}]


class TestTicketCommand(BaseTest):
    def setUp(self):
        super().setUp()
        # Old organization by default, so eligibility is decided by plan tier rather than the new-org grace period
        self.team.organization.created_at = timezone.now() - timedelta(days=100)
        self.team.organization.save()
        self.command = TicketCommand(self.team, self.user)

    def _config(self) -> RunnableConfig:
        return RunnableConfig(configurable={"thread_id": "test-conversation-id"})

    async def _execute_with_features(
        self, available_product_features: list | None, state: AssistantState | None = None
    ) -> AssistantMessage:
        state = state or AssistantState(messages=[HumanMessage(content="/ticket")])

        def set_features() -> None:
            self.team.organization.available_product_features = available_product_features
            self.team.organization.save()

        await sync_to_async(set_features)()
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

        message = await self._execute_with_features(PAID_FEATURES, state=state)

        self.assertEqual(message.content, "Summary of the conversation")
        mock_summarize.assert_called_once()

    async def test_execute_first_message_prompts_for_input(self):
        message = await self._execute_with_features(PAID_FEATURES)

        self.assertIn(DESCRIBE_ISSUE_MARKER, message.content.lower())

    @parameterized.expand(
        [
            ("paid_entitlements", PAID_FEATURES, True),
            ("no_entitlements", [], False),
            ("entitlements_never_synced", None, False),
        ]
    )
    async def test_eligibility_follows_plan_tier(self, _name, available_product_features, allowed):
        message = await self._execute_with_features(available_product_features)

        if allowed:
            self.assertIn(DESCRIBE_ISSUE_MARKER, message.content.lower())
        else:
            self.assertIn(UPGRADE_MARKER, message.content)

    async def test_new_org_allowed_without_entitlements(self):
        self.team.organization.created_at = timezone.now() - timedelta(days=30)
        await sync_to_async(self.team.organization.save)()

        message = await self._execute_with_features(None)

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
