from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from ee.hogai.llm import MaxChatOpenAI

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.title_generator.prompts import TITLE_GENERATION_PROMPT
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage


class TitleGeneratorNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        human_message = find_last_message_of_type(state.messages, HumanMessage)
        if not human_message:
            return None

        conversation = self._get_conversation(config["configurable"]["thread_id"])
        if not conversation or conversation.title:
            return None

        runnable = (
            ChatPromptTemplate.from_messages([("system", TITLE_GENERATION_PROMPT), ("user", "{user_input}")])
            | self._model
            | StrOutputParser()
        )

        title = runnable.invoke({"user_input": human_message.content}, config=config)

        conversation.title = title[: Conversation.TITLE_MAX_LENGTH].strip()
        conversation.save()

        return None

    @property
    def _model(self):
        return MaxChatOpenAI(
            model="gpt-4.1-nano",
            temperature=0.7,
            max_completion_tokens=100,
            user=self._user,
            team=self._team,
        )
