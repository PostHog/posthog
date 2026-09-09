from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception

from posthog.schema import AssistantMessage

from posthog.sync import database_sync_to_async

from products.posthog_ai.backend.services.usage.report import build_usage_report

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
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

            # The report reads Postgres and ClickHouse, so it runs in a worker thread; on the event
            # loop the ORM reads raise SynchronousOnlyOperation.
            report = await database_sync_to_async(build_usage_report, thread_sensitive=False)(
                self._team,
                conversation_id=UUID(str(conversation_id)),
                billing_context=config.get("configurable", {}).get("billing_context"),
            )

            return PartialAssistantState(messages=[AssistantMessage(content=report.message, id=str(uuid4()))])

        except Exception as e:
            capture_exception(e)
            raise Exception("PostHog AI usage information query failed. Please try again later.") from e
