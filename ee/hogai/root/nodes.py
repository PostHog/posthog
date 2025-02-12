import datetime
from typing import Literal, cast
from uuid import uuid4

from langchain_core.messages import AIMessage as LangchainAIMessage, BaseMessage, HumanMessage as LangchainHumanMessage
from langchain_core.output_parsers import PydanticToolsParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from ee.hogai.root.prompts import POST_QUERY_USER_PROMPT, ROOT_INSIGHT_DESCRIPTION_PROMPT, ROOT_SYSTEM_PROMPT
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantMessage, HumanMessage, RouterMessage

RouteName = Literal["trends", "funnel", "retention", "end"]


# Lower casing matters here. Do not change it.
class retrieve_data_for_question(BaseModel):
    """
    Retrieve results for a specific data question.
    """

    query_description: str = Field(description="The description of the query being asked.")
    query_kind: Literal["trends", "funnel", "retention"] = Field(description=ROOT_INSIGHT_DESCRIPTION_PROMPT)


root_tools_parser = PydanticToolsParser(tools=[retrieve_data_for_question])


class RootNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ROOT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        ) + self._construct_messages(state)
        chain = prompt | self._model

        utc_now = datetime.datetime.now(datetime.UTC)
        project_now = utc_now.astimezone(self._team.timezone_info)

        message: LangchainAIMessage = chain.invoke(
            {
                "core_memory": self.core_memory_text,
                "utc_datetime_display": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_datetime_display": project_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_timezone": self._team.timezone_info.tzname(utc_now),
            },
            config,
        )

        state_messages: list[BaseModel] = []

        if message.content:  # Should practically always be set, but with tool case this is not _guaranteed_
            state_messages.append(AssistantMessage(content=str(message.content), id=str(uuid4())))

        if message.tool_calls:
            try:
                tool_calls: list[retrieve_data_for_question] = root_tools_parser.invoke(message, config=config)
            except ValidationError:
                pass  # TODO: Retry generation using this error message
            else:
                state_messages.append(
                    RouterMessage(
                        content=tool_calls[0].query_kind,
                        id=str(uuid4()),
                    )
                )

        return PartialAssistantState(messages=state_messages)

    def router(self, state: AssistantState) -> RouteName:
        last_message = state.messages[-1]
        if isinstance(last_message, RouterMessage):
            return cast(RouteName, last_message.content)
        return "end"

    @property
    def _model(self):
        # Research suggests temperature is not _massively_ correlated with creativity, hence even in this very
        # conversational context we're using a temperature of 0, for near determinism (https://arxiv.org/html/2405.00492v1)
        return ChatOpenAI(model="gpt-4o", temperature=0.0, streaming=True, stream_usage=True).bind_tools(
            [retrieve_data_for_question], parallel_tool_calls=False
        )

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        history: list[BaseMessage] = []
        for message in state.messages:
            if isinstance(message, HumanMessage):
                history.append(LangchainHumanMessage(content=message.content))
            elif isinstance(message, AssistantMessage):
                history.append(LangchainAIMessage(content=message.content))
            elif isinstance(message, RouterMessage):
                history.append(LangchainAIMessage(content=f"Generating a {message.content} query…"))
        if state.messages and isinstance(state.messages[-1], AssistantMessage):
            history.append(LangchainHumanMessage(content=POST_QUERY_USER_PROMPT))
        return history
