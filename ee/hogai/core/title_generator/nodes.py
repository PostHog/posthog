import logging
from typing import cast

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from posthog.schema import HumanMessage

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.core.node import AssistantNode
from ee.hogai.core.title_generator.prompts import TITLE_AND_TOPIC_GENERATION_PROMPT, TITLE_GENERATION_PROMPT
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.utils.feature_flags import has_conversation_topic_feature_flag
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import ConversationTitleAction

logger = logging.getLogger(__name__)


class TitleAndTopic(BaseModel):
    title: str = Field(description="A crisp conversation title, ≤ 8 words, sentence case.")
    topic: Conversation.Topic = Field(description="The PostHog product domain the user's first question is about.")


class TitleGeneratorNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        human_message = find_last_message_of_type(state.messages, HumanMessage)
        if not human_message:
            return None

        conversation = self._get_conversation(config["configurable"]["thread_id"])
        if not conversation or conversation.title:
            return None

        if has_conversation_topic_feature_flag(self._team, self._user):
            title, topic = self._generate_title_and_topic(human_message.content, config)
        else:
            title, topic = self._generate_title_only(human_message.content, config), None

        conversation.title = title[: Conversation.TITLE_MAX_LENGTH].strip()
        if topic is not None:
            conversation.topic = topic
        conversation.save()

        # Emit the title and topic to the stream so the frontend updates immediately
        try:
            writer = get_stream_writer()
        except RuntimeError:
            pass  # Not in a streaming context (e.g. testing)
        else:
            writer(ConversationTitleAction(title=conversation.title, topic=conversation.topic))

        return None

    def _generate_title_only(self, user_input: str, config: RunnableConfig) -> str:
        runnable = (
            ChatPromptTemplate.from_messages([("system", TITLE_GENERATION_PROMPT), ("user", "{user_input}")])
            | self._model
            | StrOutputParser()
        )
        return runnable.invoke({"user_input": user_input}, config=config)

    def _generate_title_and_topic(self, user_input: str, config: RunnableConfig) -> tuple[str, str | None]:
        try:
            runnable = (
                ChatPromptTemplate.from_messages(
                    [("system", TITLE_AND_TOPIC_GENERATION_PROMPT), ("user", "{user_input}")]
                )
                | self._topic_model
            )
            result = cast(TitleAndTopic, runnable.invoke({"user_input": user_input}, config=config))
            return result.title, result.topic
        except Exception:
            # Never break title generation on a classification failure, fall back to title-only.
            logger.exception("title_topic_generation_failed, falling back to title-only")
            return self._generate_title_only(user_input, config), None

    def _build_model(self, *, max_completion_tokens: int, topic_classification: bool) -> MaxChatOpenAI:
        return MaxChatOpenAI(
            model="gpt-4.1-nano",
            temperature=0.7,
            max_completion_tokens=max_completion_tokens,
            user=self._user,
            team=self._team,
            streaming=False,
            stream_usage=False,
            disable_streaming=True,
            billable=True,
            posthog_properties={"topic_classification": topic_classification},
        )

    @property
    def _model(self):
        return self._build_model(max_completion_tokens=100, topic_classification=False)

    @property
    def _topic_model(self):
        return self._build_model(max_completion_tokens=200, topic_classification=True).with_structured_output(
            TitleAndTopic, method="json_schema", include_raw=False
        )
