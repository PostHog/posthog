from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.title_generator.prompts import TITLE_GENERATION_PROMPT
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import HumanMessage


class TitleGeneratorNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        human_message = find_last_message_of_type(state.messages, HumanMessage)
        if not human_message:
            return None

        conversation = self._get_conversation(config["configurable"]["thread_id"])
        if not conversation:
            return None

        title = (
            self._model.invoke(
                ChatPromptTemplate.from_messages(
                    [("system", TITLE_GENERATION_PROMPT), ("user", human_message.content)]
                ),
                config,
            )
            | StrOutputParser()
        )

        conversation.title = title
        conversation.save()

        return None

    def should_run(self, state: AssistantState) -> bool:
        human_messages_count = sum(1 for message in state.messages if isinstance(message, HumanMessage))
        return human_messages_count == 1

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1-nano", temperature=0.7, max_completion_tokens=100)
