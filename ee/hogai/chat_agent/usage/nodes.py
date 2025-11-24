from uuid import uuid4

from django.utils import timezone

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from langgraph.types import Send
from posthoganalytics import capture_exception

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.memory.nodes import MemoryOnboardingNode
from ee.hogai.chat_agent.usage.queries import (
    POSTHOG_AI_USAGE_REPORT_ASSISTANT_MESSAGE_TITLE,
    format_usage_message,
    get_ai_credits_for_conversation,
    get_ai_credits_for_team,
    get_ai_free_tier_credits,
    get_conversation_start_time,
    get_past_month_start,
)
from ee.hogai.core.agent_modes.const import SLASH_COMMAND_USAGE
from ee.hogai.core.node import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName


class UsageNode(AssistantNode):
    """
    Node that handles the /usage slash command.
    Shows PostHog AI credit usage for the current conversation and billing period.
    """

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        last_message = state.messages[-1] if state.messages else None

        if not isinstance(last_message, HumanMessage) or last_message.content.strip() != SLASH_COMMAND_USAGE:
            # Not a usage command, return None for passthrough
            return None

        try:
            # Get conversation ID from config
            conversation_id = config.get("configurable", {}).get("thread_id")
            if not conversation_id:
                return PartialAssistantState(
                    messages=[AssistantMessage(content="Unable to retrieve conversation information.", id=str(uuid4()))]
                )

            conversation_start = await sync_to_async(get_conversation_start_time)(conversation_id)
            if not conversation_start:
                return PartialAssistantState(
                    messages=[AssistantMessage(content="Unable to retrieve conversation start time.", id=str(uuid4()))]
                )

            past_month_start = get_past_month_start()
            now = timezone.now()

            # Calculate credits for current conversation
            conversation_credits = await sync_to_async(get_ai_credits_for_conversation, thread_sensitive=False)(
                team_id=self._team.id,
                conversation_id=conversation_id,
                begin=conversation_start,
                end=now,
            )

            # Calculate credits for past 30 days (capped at GA launch)
            past_month_credits = await sync_to_async(get_ai_credits_for_team, thread_sensitive=False)(
                team_id=self._team.id,
                begin=past_month_start,
                end=now,
            )

            # Get free tier credits for this team ID
            free_tier_credits = get_ai_free_tier_credits(self._team.id)

            usage_message = format_usage_message(
                conversation_credits=conversation_credits,
                past_month_credits=past_month_credits,
                free_tier_credits=free_tier_credits,
                conversation_start=conversation_start,
                past_month_start=past_month_start,
            )

            return PartialAssistantState(messages=[AssistantMessage(content=usage_message, id=str(uuid4()))])

        except Exception as e:
            capture_exception(e)
            raise Exception("PostHog AI usage information query failed. Please try again later.")

    def router(self, state: AssistantState) -> AssistantNodeName | list[Send]:
        last_message = state.messages[-1] if state.messages else None

        if isinstance(last_message, AssistantMessage):
            if POSTHOG_AI_USAGE_REPORT_ASSISTANT_MESSAGE_TITLE in last_message.content:
                return AssistantNodeName.END

        send_list = [
            Send(AssistantNodeName.ROOT, state),
            Send(AssistantNodeName.MEMORY_COLLECTOR, state),
        ]

        memory_onboarding_should_run = MemoryOnboardingNode(self._team, self._user).should_run_onboarding_at_start(
            state
        )
        if memory_onboarding_should_run == "memory_onboarding":
            send_list.append(Send(AssistantNodeName.MEMORY_ONBOARDING, state))

        return send_list
