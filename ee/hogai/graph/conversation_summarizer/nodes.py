from abc import abstractmethod
from collections.abc import Sequence

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import XMLOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.conversation_summarizer.prompts import SYSTEM_PROMPT, USER_PROMPT


class ConversationSummarizer:
    async def summarize(self, messages: Sequence[BaseMessage], config: RunnableConfig) -> str:
        prompt = (
            ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT)])
            + messages
            + ChatPromptTemplate.from_messages([("user", USER_PROMPT)])
        )
        model = self._get_model()
        chain = prompt | model | XMLOutputParser(tags=["analysis", "summary"])
        response: dict[str, str] = await chain.ainvoke({}, config)
        return response["summary"]

    @abstractmethod
    def _get_model(self): ...


class AnthropicConversationSummarizer(ConversationSummarizer):
    def _get_model(self):
        return ChatAnthropic(
            model="claude-sonnet-4-0",
            streaming=False,
            stream_usage=False,
            max_tokens=8192,
        )
