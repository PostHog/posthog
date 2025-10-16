import re
from abc import abstractmethod
from collections.abc import Sequence

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from posthog.models import Team, User

from ee.hogai.graph.conversation_summarizer.prompts import SYSTEM_PROMPT, USER_PROMPT
from ee.hogai.llm import MaxChatAnthropic


class ConversationSummarizer:
    def __init__(self, team: Team, user: User):
        self._user = user
        self._team = team

    async def summarize(self, messages: Sequence[BaseMessage]) -> str:
        prompt = (
            ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT)])
            + messages
            + ChatPromptTemplate.from_messages([("user", USER_PROMPT)])
        )
        model = self._get_model()
        chain = prompt | model | StrOutputParser() | self._parse_xml_tags
        response: str = await chain.ainvoke({})  # Do not pass config here, so the node doesn't stream
        return response

    @abstractmethod
    def _get_model(self): ...

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
            model="claude-sonnet-4-0",
            streaming=False,
            stream_usage=False,
            max_tokens=8192,
            disable_streaming=True,
            user=self._user,
            team=self._team,
        )
