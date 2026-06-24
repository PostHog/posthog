from uuid import uuid4

from django.utils import timezone

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception

from posthog.schema import AssistantMessage

from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.chat_agent.slash_commands.commands.usage.queries import (
    format_usage_message,
    get_ai_credits_for_conversation,
    get_ai_credits_for_team,
    get_ai_free_tier_credits,
    get_ai_usage_period,
    get_conversation_start_time,
)
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class UsageCommand(SlashCommand):
    """
    Handles the /usage slash command.
    Shows PostHog AI credit usage for the current conversation and billing period.
    """

    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        try:
            conversation_id = config.get("configurable", {}).get("thread_id")
            if not conversation_id:
                return PartialAssistantState(
                    messages=[AssistantMessage(content="Unable to retrieve conversation information.", id=str(uuid4()))]
                )

            conversation_start = await database_sync_to_async(get_conversation_start_time)(conversation_id)
            if not conversation_start:
                return PartialAssistantState(
                    messages=[AssistantMessage(content="Unable to retrieve conversation start time.", id=str(uuid4()))]
                )

            usage_period = await database_sync_to_async(get_ai_usage_period)(
                self._team, config.get("configurable", {}).get("billing_context")
            )

            conversation_credits = await sync_to_async(get_ai_credits_for_conversation, thread_sensitive=False)(
                team_id=self._team.id,
                conversation_id=conversation_id,
                begin=conversation_start,
                end=timezone.now(),
            )

            period_credits = (
                await sync_to_async(get_ai_credits_for_team, thread_sensitive=False)(
                    team_id=self._team.id,
                    begin=usage_period.query_start,
                    end=usage_period.end,
                )
                if usage_period.query_start < usage_period.end
                else 0
            )

            free_tier_credits = get_ai_free_tier_credits(self._team.id)

            usage_message = format_usage_message(
                conversation_credits=conversation_credits,
                period_credits=period_credits,
                free_tier_credits=free_tier_credits,
                conversation_start=conversation_start,
                usage_period=usage_period,
            )

            return PartialAssistantState(messages=[AssistantMessage(content=usage_message, id=str(uuid4()))])

        except Exception as e:
            capture_exception(e)
            raise Exception("PostHog AI usage information query failed. Please try again later.") from e
