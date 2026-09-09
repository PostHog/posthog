import asyncio
from datetime import UTC, datetime
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.exceptions import SynchronousOnlyOperation

from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from products.posthog_ai.backend.models.assistant import Conversation
from products.posthog_ai.backend.services.usage.credits import AiUsagePeriod

from ee.hogai.chat_agent.slash_commands.commands.usage.command import UsageCommand
from ee.hogai.utils.types import AssistantState

REPORT_MODULE = "products.posthog_ai.backend.services.usage.report"


class TestUsageCommand(BaseTest):
    def test_execute_runs_usage_period_off_event_loop(self):
        # Without a billing context, get_ai_usage_period falls back to team.organization.usage, a sync
        # ORM access. It must run off the event loop or Django raises SynchronousOnlyOperation, which the
        # command would swallow into a generic failure. This guard mimics that check: it raises only when
        # get_ai_usage_period executes directly on the running loop.
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        config = RunnableConfig(configurable={"thread_id": str(conversation.id)})
        state = AssistantState(messages=[HumanMessage(content="/usage")])

        def usage_period_guarded(*args, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return AiUsagePeriod(
                    label="Past 30 days",
                    start=datetime(2026, 5, 1, tzinfo=UTC),
                    end=datetime(2026, 6, 1, tzinfo=UTC),
                    query_start=datetime(2026, 5, 1, tzinfo=UTC),
                )
            raise SynchronousOnlyOperation(
                "You cannot call this from an async context - use a thread or sync_to_async."
            )

        with (
            patch(f"{REPORT_MODULE}.get_ai_usage_period", side_effect=usage_period_guarded),
            patch(f"{REPORT_MODULE}.get_ai_credits_for_conversation", return_value=10),
            patch(f"{REPORT_MODULE}.get_ai_credits_for_team", return_value=100),
            patch(f"{REPORT_MODULE}.get_ai_free_tier_credits", return_value=2000),
        ):
            result = async_to_sync(UsageCommand(self.team, self.user).execute)(config, state)

        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        content = cast(str, message.content)
        self.assertIn("PostHog AI usage", content)
        self.assertIn("**Current conversation**: 10 credits", content)
        self.assertNotIn("query failed", content)
