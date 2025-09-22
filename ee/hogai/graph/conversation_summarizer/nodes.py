from abc import abstractmethod

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCallMessage

from posthog.models import Team, User

from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.anthropic import convert_to_anthropic_messages
from ee.hogai.utils.types import AssistantState

PROMPT = """
You are Max, the friendly and knowledgeable AI assistant of PostHog.
You are tasked with summarizing conversations.
""".strip()


class ConversationSummarizer:
    def __init__(self, team: Team, user: User):
        self._user = user
        self._team = team

    async def summarize(self, state: AssistantState, config: RunnableConfig) -> str:
        prompt = self._construct_messages(state)
        model = self._get_model(state)
        chain = prompt | model | StrOutputParser()
        response = await chain.ainvoke({}, config)
        return response

    @abstractmethod
    def _get_model(self, state: AssistantState):
        raise NotImplementedError

    def _construct_messages(self, state: AssistantState):
        tool_result_messages = {
            message.tool_call_id: message for message in state.messages if isinstance(message, AssistantToolCallMessage)
        }

        prompt = ChatPromptTemplate.from_messages([("system", PROMPT)]) + convert_to_anthropic_messages(
            state.messages, tool_result_messages
        )
        return prompt


class AnthropicConversationSummarizer(ConversationSummarizer):
    def _get_model(self, state: AssistantState):
        return MaxChatAnthropic(
            model="claude-sonnet-4-0",
            streaming=False,
            stream_usage=False,
            user=self._user,
            team=self._team,
            max_tokens=8192,
            conversation_start_dt=state.start_dt,
        )
