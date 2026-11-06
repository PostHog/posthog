import re
import datetime
from abc import abstractmethod
from collections.abc import Sequence

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from posthog.models import Team, User

from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.anthropic import add_cache_control

from .prompts import FINAL_TURN_PROMPT, SUMMARIZATION_INSTRUCTION_PROMPT, SYSTEM_PROMPT


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
        # The summarization instruction carries no per-conversation data, so it leads the prompt to
        # keep the fixed prefix contiguous and identical between calls. Everything that changes per
        # call follows it: the project context `MaxChatMixin` appends to the system block, then the
        # conversation itself.
        return (
            ChatPromptTemplate.from_messages([self._construct_system_message()])
            + messages
            # The conversation can end with an assistant message, which the Anthropic API rejects as
            # a prefill. This turn keeps the request ending on a user message, and repeats the task
            # after a conversation that can reach the full 400k-token window.
            + ChatPromptTemplate.from_messages([("user", FINAL_TURN_PROMPT)])
        )

    def _construct_system_message(self) -> BaseMessage:
        return SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{SUMMARIZATION_INSTRUCTION_PROMPT}")

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

    def _construct_system_message(self) -> BaseMessage:
        # The 1h TTL outlives the 5m one between compactions, which are minutes to hours apart.
        return add_cache_control(super()._construct_system_message(), ttl="1h")

    def _construct_messages(self, messages: Sequence[BaseMessage]):
        """Removes cache_control headers, so the only breakpoint is the one on the fixed prefix.

        The agent marks the last message of the conversation it hands over, which would make
        Anthropic write a cache entry for a ~400k-token prefix that no later call can read, because
        each compaction sends a conversation only it has.
        """
        messages_without_cache: list[BaseMessage] = []
        for message in messages:
            if isinstance(message.content, list):
                message = message.model_copy(deep=True)
                for content in message.content:
                    if isinstance(content, dict) and "cache_control" in content:
                        content.pop("cache_control")
            messages_without_cache.append(message)

        return super()._construct_messages(messages_without_cache)
