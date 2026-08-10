import re
import datetime
from abc import abstractmethod
from collections.abc import Sequence

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from posthog.models import Team, User

from ee.hogai.llm import MaxChatAnthropic

from .prompts import SYSTEM_PROMPT, USER_PROMPT


class ConversationSummarizer:
    def __init__(self, team: Team, user: User, conversation_start_dt: datetime.datetime | None = None):
        self._user = user
        self._team = team
        self._conversation_start_dt = conversation_start_dt

    async def summarize(self, messages: Sequence[BaseMessage]) -> str:
        prompt = self._construct_messages(messages)
        model = self._get_model()
        chain = prompt | model | StrOutputParser() | self._parse_xml_tags
        response: str = await chain.ainvoke({})  # Do not pass config here, so the node doesn't stream
        return response

    @abstractmethod
    def _get_model(self): ...

    def _construct_messages(self, messages: Sequence[BaseMessage]):
        return (
            ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT)])
            + messages
            + ChatPromptTemplate.from_messages([("user", USER_PROMPT)])
        )

    def _parse_xml_tags(self, message: str) -> str:
        """
        Extract analysis and summary tags from a message.

        Args:
            message: The message content to parse

        Returns:
            Summary (falls back to original message if not present)
        """
        summary = message  # fallback to original message

        # Extract summary tag content
        summary_match = re.search(r"<summary>(.*?)</summary>", message, re.DOTALL | re.IGNORECASE)
        if summary_match:
            summary = summary_match.group(1).strip()

        return summary


class AnthropicConversationSummarizer(ConversationSummarizer):
    def _get_model(self):
        return MaxChatAnthropic(
            # Sonnet 5 has a 1M token limit, so it can compact a conversation of any size we let
            # grow. Haiku's 200k limit no longer covers CONVERSATION_WINDOW_SIZE.
            model="claude-sonnet-5",
            streaming=False,
            stream_usage=False,
            max_tokens=16384,
            disable_streaming=True,
            # Sonnet 5 thinks by default, and `max_tokens` caps thinking plus response text
            # together. A thinking overrun here would truncate the summary, which silently drops
            # the conversation history it is supposed to preserve. The prompt already asks for an
            # explicit `<analysis>` pass before `<summary>`, so the reasoning happens either way.
            thinking={"type": "disabled"},
            # Without this, `MaxChatMixin._get_project_org_user_variables` stamps the current
            # wall-clock second into the injected context message.
            conversation_start_dt=self._conversation_start_dt,
            user=self._user,
            team=self._team,
            billable=True,
        )

    def _construct_messages(self, messages: Sequence[BaseMessage]):
        """Removes cache_control headers."""
        messages_without_cache: list[BaseMessage] = []
        for message in messages:
            if isinstance(message.content, list):
                message = message.model_copy(deep=True)
                for content in message.content:
                    if isinstance(content, dict) and "cache_control" in content:
                        content.pop("cache_control")
            messages_without_cache.append(message)

        return super()._construct_messages(messages_without_cache)
