import datetime
from typing import Literal, cast
from uuid import uuid4

from django.conf import settings
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.output_parsers import PydanticToolsParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from ee.hogai.root.prompts import (
    ROOT_HARD_LIMIT_REACHED_PROMPT,
    ROOT_INSIGHT_DESCRIPTION_PROMPT,
    ROOT_SYSTEM_PROMPT,
    ROOT_VALIDATION_EXCEPTION_PROMPT,
)
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage

RouteName = Literal["trends", "funnel", "retention", "root", "end", "docs"]


# Lower casing matters here. Do not change it.
class create_and_query_insight(BaseModel):
    """
    Retrieve results for a specific data question by creating a query or iterate on a previous query.
    This tool only retrieves data for a single insight at a time.
    The `trends` insight type is the only insight that can display multiple trends insights in one request.
    All other insight types strictly return data for a single insight.
    """

    query_description: str = Field(description="The description of the query being asked.")
    query_kind: Literal["trends", "funnel", "retention"] = Field(description=ROOT_INSIGHT_DESCRIPTION_PROMPT)


class search_documentation(BaseModel):
    """
    Search PostHog documentation to answer questions about features, concepts, and usage.
    Use this tool when the user asks about how to use PostHog, its features, or needs help understanding concepts.
    Don't use this tool if the necessary information is already in the conversation.
    """


RootToolCall = create_and_query_insight | search_documentation
root_tools_parser = PydanticToolsParser(tools=[create_and_query_insight, search_documentation])


class RootNode(AssistantNode):
    MAX_TOOL_CALLS = 4

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ROOT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        ) + self._construct_messages(state)
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
            messages=[
                AssistantMessage(
                    content=str(message.content),
                    tool_calls=[
                        AssistantToolCall(id=tool_call["id"], name=tool_call["name"], args=tool_call["args"])
                        for tool_call in message.tool_calls
                    ],
                    id=str(uuid4()),
                ),
            ]
        )

    def _get_model(self, state: AssistantState):
        # Research suggests temperature is not _massively_ correlated with creativity, hence even in this very
        # conversational context we're using a temperature of 0, for near determinism (https://arxiv.org/html/2405.00492v1)
        base_model = ChatOpenAI(model="gpt-4", temperature=0.0, streaming=True, stream_usage=True)

        # The agent can now be involved in loops. Since insight building is an expensive operation, we want to limit a recursion depth.
        # This will remove the functions, so the agent don't have any other option but to exit.
        if self._is_hard_limit_reached(state):
            return base_model

        available_tools: list[type[BaseModel]] = [create_and_query_insight]
        if settings.INKEEP_API_KEY:
            available_tools.append(search_documentation)

        return base_model.bind_tools(available_tools, strict=True, parallel_tool_calls=False)

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        # `assistant` messages must be contiguous with the respective `tool` messages.
        tool_result_messages = {
            message.tool_call_id: message for message in state.messages if isinstance(message, AssistantToolCallMessage)
        }

        history: list[BaseMessage] = []
        for message in state.messages:
            if isinstance(message, HumanMessage):
                history.append(LangchainHumanMessage(content=message.content))
            elif isinstance(message, AssistantMessage):
                # Filter out tool calls without a tool response, so the completion doesn't fail.
                tool_calls = [
                    tool for tool in message.model_dump()["tool_calls"] or [] if tool["id"] in tool_result_messages
                ]

                history.append(LangchainAIMessage(content=message.content, tool_calls=tool_calls))

                # Append associated tool call messages.
                for tool_call in tool_calls:
                    history.append(
                        LangchainToolMessage(
                            content=tool_result_messages[tool_call["id"]].content, tool_call_id=tool_call["id"]
                        )
                    )

        if self._is_hard_limit_reached(state):
            history.append(LangchainHumanMessage(content=ROOT_HARD_LIMIT_REACHED_PROMPT))

        return history

    def _is_hard_limit_reached(self, state: AssistantState) -> bool:
        return state.root_tool_calls_count is not None and state.root_tool_calls_count >= self.MAX_TOOL_CALLS


class RootNodeTools(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage) or not last_message.tool_calls:
            # Reset tools.
            return PartialAssistantState(root_tool_calls_count=0)

        tool_call_count = state.root_tool_calls_count or 0

        try:
            langchain_msg = self._construct_langchain_ai_message(last_message)
            parsed_tool_calls: list[RootToolCall] = root_tools_parser.invoke(langchain_msg)
        except ValidationError as e:
            content = (
                ChatPromptTemplate.from_template(ROOT_VALIDATION_EXCEPTION_PROMPT, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(content=str(content), id=str(uuid4()), tool_call_id=last_message.id)
                ],
                root_tool_calls_count=tool_call_count + 1,
            )

        if len(parsed_tool_calls) != 1:
            raise ValueError("Expected exactly one tool call.")

        tool_call = parsed_tool_calls[0]
        if isinstance(tool_call, create_and_query_insight):
            return PartialAssistantState(
                root_tool_call_id=langchain_msg.tool_calls[-1]["id"],
                root_tool_insight_plan=tool_call.query_description,
                root_tool_insight_type=tool_call.query_kind,
                root_tool_calls_count=tool_call_count + 1,
            )
        elif isinstance(tool_call, search_documentation):
            return PartialAssistantState(
                root_tool_call_id=langchain_msg.tool_calls[-1]["id"],
                root_tool_insight_plan=None,  # No insight plan for docs search
                root_tool_insight_type=None,  # No insight type for docs search
                root_tool_calls_count=tool_call_count + 1,
            )
        else:
            raise ValueError(f"Unsupported tool call: {type(tool_call)}")

    def router(self, state: AssistantState) -> RouteName:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantToolCallMessage):
            return "root"
        if state.root_tool_call_id:
            if state.root_tool_insight_type:
                return cast(RouteName, state.root_tool_insight_type)
            # If no insight type is set but we have a tool call ID, it must be a docs search
            return "docs"
        return "end"

    def _construct_langchain_ai_message(self, message: AssistantMessage):
        return LangchainAIMessage(content=message.content, tool_calls=message.model_dump()["tool_calls"] or [])
