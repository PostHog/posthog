import datetime
from typing import Literal, cast
from uuid import uuid4

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from products.data_warehouse.backend.prompts import SQL_ASSISTANT_SYSTEM_PROMPT, SQL_ASSISTANT_HOGQL_QUERY_PROMPT
from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantMessage, HumanMessage, AssistantToolCall, AssistantContextualTool
from pydantic import BaseModel


class generate_hogql_query(BaseModel):
    """
    Generate a hogQL query to answer the user's question.
    """


class SQLAssistantNode(AssistantNode):
    """
    A node that provides thinking/reasoning about how to approach a query before implementation.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        # Get the message history
        history = self._construct_messages(state)

        # Create the prompt with the thinking system prompt
        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", SQL_ASSISTANT_SYSTEM_PROMPT),
                    ("human", SQL_ASSISTANT_HOGQL_QUERY_PROMPT),
                ],
                template_format="mustache",
            )
            + history
        )

        # Get the model
        model = ChatOpenAI(model="gpt-4o", temperature=0.0, streaming=True)
        model = model.bind_tools([generate_hogql_query])

        generate_hogql_query_config = self._get_contextual_tools(config).get(
            AssistantContextualTool.GENERATE_HOGQL_QUERY, {}
        )

        # Create the chain
        chain = prompt | model

        # Get current time info
        utc_now = datetime.datetime.now(datetime.UTC)
        project_now = utc_now.astimezone(self._team.timezone_info)

        # Invoke the chain
        message = chain.invoke(
            {
                "utc_datetime_display": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_datetime_display": project_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_timezone": self._team.timezone_info.tzname(utc_now),
                **generate_hogql_query_config,
            },
            config,
        )
        message = cast(LangchainAIMessage, message)

        # Return the result as a PartialAssistantState
        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=str(message.content),
                    tool_calls=[
                        AssistantToolCall(id=tool_call["id"], name=tool_call["name"], args=tool_call["args"])
                        for tool_call in message.tool_calls
                    ],
                    id=str(uuid4()),
                ),
            ],
        )

    def router(self, state: AssistantState) -> Literal["next"]:
        """
        Router for the thinking node - always routes to the next node (SQL planner).
        This prevents looping back to itself.
        """
        last_message = state.messages[-1]
        # only possible tool call is generate_hogql_query for now
        if last_message.tool_calls:
            return "next"
        return "end"

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        """
        Construct a message history for the thinking node.
        """
        # Convert messages to the format expected by LangChain
        history: list[BaseMessage] = []
        for message in state.messages:
            if isinstance(message, HumanMessage):
                history.append(LangchainHumanMessage(content=message.content, id=message.id))
            elif isinstance(message, AssistantMessage):
                history.append(LangchainAIMessage(content=message.content, id=message.id))

        return history
