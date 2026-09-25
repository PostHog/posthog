import re
import datetime
from abc import abstractmethod
from collections.abc import Sequence

import structlog
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from posthoganalytics import capture_exception
from prometheus_client import Counter

from posthog.models import Team, User

from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.anthropic import add_cache_control
from ee.hogai.utils.exceptions import LLM_CLIENT_EXCEPTIONS

from .input_budget import ConversationInputBudget
from .prompts import FINAL_TURN_PROMPT, SUMMARIZATION_INSTRUCTION_PROMPT, SYSTEM_PROMPT

logger = structlog.get_logger(__name__)

SUMMARIZER_INPUT_RETRY_COUNTER = Counter(
    "posthog_ai_summarizer_input_too_long_retries_total",
    "Conversation summarizations the model rejected as too long and that were retried smaller",
)


class ConversationSummarizer:
    MAX_INPUT_TOKENS = 600_000
    """
    Determines the largest conversation the summarizer sends in one request.

    Sits well under the summarizer model's 1M context limit, because the budget is spent against a
    character estimate that undercounts dense JSON and non-English text. It is also well above
    `CONVERSATION_WINDOW_SIZE`, so a conversation that grew as intended reaches the model whole and
    only a window that overshot the compaction threshold pays for it.
    """

    RETRY_INPUT_TOKENS = 150_000
    """
    Determines the budget of the second attempt, after the model rejected the first as too long.
    """

    def __init__(self, team: Team, user: User, conversation_start_dt: datetime.datetime | None = None):
        self._user = user
        self._team = team
        self._conversation_start_dt = conversation_start_dt

    async def summarize(self, messages: Sequence[BaseMessage]) -> str:
        try:
            return await self._summarize(messages, self.MAX_INPUT_TOKENS)
        except LLM_CLIENT_EXCEPTIONS as e:
            if not self._is_input_too_long(e):
                raise
            # A rejection here is unrecoverable if it stands: every later turn re-enters compaction
            # and fails the same way, so the conversation can never be used again. Trimming harder
            # costs summary detail, which the next turn can still work from.
            SUMMARIZER_INPUT_RETRY_COUNTER.inc()
            logger.warning("Conversation summarization was rejected as too long, retrying on a smaller budget")
            capture_exception(e)
        return await self._summarize(messages, self.RETRY_INPUT_TOKENS)

    async def _summarize(self, messages: Sequence[BaseMessage], max_input_tokens: int) -> str:
        prompt = self._construct_messages(ConversationInputBudget(max_input_tokens).apply(messages))
        model = self._get_model()
        chain = prompt | model | StrOutputParser() | self._parse_xml_tags
        response: str = await chain.ainvoke({})  # Do not pass config here, so the node doesn't stream
        return response

    def _is_input_too_long(self, error: Exception) -> bool:
        message = str(error).lower()
        return any(marker in message for marker in ("prompt is too long", "maximum context length"))

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
            # Sonnet 5 has a 1M token limit, which `MAX_INPUT_TOKENS` keeps the request under.
            # Haiku's 200k limit no longer covers CONVERSATION_WINDOW_SIZE.
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
