from collections.abc import Sequence
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.types import AssistantMessageUnion, AssistantState, PartialAssistantState

from .prompts import SUPPORT_SUMMARIZER_SYSTEM_PROMPT, SUPPORT_SUMMARIZER_USER_PROMPT


class TicketCommand(SlashCommand):
    """
    Handles the /ticket slash command.
    Summarizes the conversation for the frontend to use when creating a support ticket.
    """

    def _is_first_message(self, state: AssistantState) -> bool:
        """Check if /ticket is the first message in the conversation."""
        human_messages = [msg for msg in state.messages if isinstance(msg, HumanMessage)]
        return len(human_messages) <= 1

    def _get_model(self) -> MaxChatAnthropic:
        # We are not billing for conversation summary since we would be billing per-ticket creation.
        return MaxChatAnthropic(
            model="claude-haiku-4-5",
            streaming=True,
            stream_usage=True,
            user=self._user,
            team=self._team,
            max_tokens=2048,
            billable=False,
        )

    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        if self._is_first_message(state):
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="I'll help you create a support ticket. Please describe your issue below.",
                        id=str(uuid4()),
                    )
                ]
            )

        summary = await self._summarize_conversation(state.messages)

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=summary,
                    id=str(uuid4()),
                )
            ]
        )

    async def _summarize_conversation(self, messages: Sequence[AssistantMessageUnion]) -> str:
        """Summarize the conversation for the support ticket."""
        summarization_header = "PostHog AI Support Ticket Summary"
        messages_list: list[SystemMessage | LangchainHumanMessage | AIMessage] = [
            SystemMessage(content=SUPPORT_SUMMARIZER_SYSTEM_PROMPT)
        ]

        for msg in messages:
            if isinstance(msg, HumanMessage):
                messages_list.append(LangchainHumanMessage(content=msg.content))
            elif isinstance(msg, AssistantMessage) and msg.content:
                messages_list.append(AIMessage(content=msg.content))

        messages_list.append(LangchainHumanMessage(content=SUPPORT_SUMMARIZER_USER_PROMPT))

        response = await self._get_model().ainvoke(messages_list)
        content = response.content
        if isinstance(content, list):
            content = "".join(str(item) for item in content)
        return f"{summarization_header}:\n\n{content}"
