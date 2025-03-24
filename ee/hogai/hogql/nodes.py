from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage as LangchainAIMessage, BaseMessage, HumanMessage as LangchainHumanMessage
from langchain_core.prompts import ChatPromptTemplate

from ee.hogai.utils.types import AssistantMessage
from ee.hogai.hogql.prompts import HOGQL_SYSTEM_PROMPT, HOGQL_HARD_LIMIT_REACHED_PROMPT
from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage


from uuid import uuid4
from typing import cast
import datetime

class HogQLNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:

        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", HOGQL_SYSTEM_PROMPT),
                ],
                template_format="mustache",
            )
        )
        chain = prompt | self._get_model(state)

        utc_now = datetime.datetime.now(datetime.UTC)
        project_now = utc_now.astimezone(self._team.timezone_info)

        message = chain.invoke(
            {
                "core_memory": self.core_memory_text,
                "utc_datetime_display": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_datetime_display": project_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_timezone": self._team.timezone_info.tzname(utc_now),
            },
            config,
        )
        message = cast(LangchainAIMessage, message)

        return PartialAssistantState(
            root_conversation_start_id=None,
            messages=[
                AssistantMessage(
                    content=str(message.content),
                    id=str(uuid4()),
                ),
            ],
        )

    def _get_model(self, state: AssistantState):
        # Research suggests temperature is not _massively_ correlated with creativity, hence even in this very
        # conversational context we're using a temperature of 0, for near determinism (https://arxiv.org/html/2405.00492v1)
        base_model = ChatOpenAI(model="gpt-4o", temperature=0.0, streaming=True, stream_usage=True)

        return base_model
    
    def _construct_and_update_messages_window(self, state: AssistantState) -> tuple[list[BaseMessage], str | None]:
        """
        Retrieves the current conversation window, finds a new window if necessary, and enforces the tool call limit.
        """

        history = self._construct_messages(state)

        # Find a new window id and trim the history to it.
        new_window_id = self._find_new_window_id(state, history)
        if new_window_id is not None:
            history = self._get_conversation_window(history, new_window_id)

        # Force the agent to stop if the tool call limit is reached.
        if self._is_hard_limit_reached(state):
            history.append(LangchainHumanMessage(content=HOGQL_HARD_LIMIT_REACHED_PROMPT))

        return history, new_window_id
    
    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        """
        Reconstruct the conversation for the agent. On this step we only care about previously asked questions and generated plans. All other messages are filtered out.
        """


        return []