import datetime
import math
from typing import Literal, TypeVar, cast
from uuid import uuid4

from django.conf import settings
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
    trim_messages,
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
from posthog.schema import (
    AssistantContextualTool,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    HumanMessage,
    FailureMessage,
)

RouteName = Literal["insights", "root", "end", "search_documentation", "session_recordings_filters"]


# Lower casing matters here. Do not change it.
class create_and_query_insight(BaseModel):
    """
    Retrieve results for a specific data question by creating a query or iterate on a previous query.
    This tool only retrieves data for a single insight at a time.
    The `trends` insight type is the only insight that can display multiple trends insights in one request.
    All other insight types strictly return data for a single insight.
    This tool is also relevant if the user asks to write SQL.
    """

    query_description: str = Field(description="The description of the query being asked.")
    query_kind: Literal["trends", "funnel", "retention", "sql"] = Field(description=ROOT_INSIGHT_DESCRIPTION_PROMPT)


class search_documentation(BaseModel):
    """
    Search PostHog documentation to answer questions about features, concepts, and usage.
    Use this tool when the user asks about how to use PostHog, its features, or needs help understanding concepts.
    Don't use this tool if the necessary information is already in the conversation.
    """


class search_session_recordings(BaseModel):
    """
    Update session recordings filters on this page, in order to search for session recordings by any criteria.
    """

    change: str = Field(description="The specific change to be made to recordings filters, briefly described.")


CONTEXTUAL_TOOL_NAME_TO_TOOL_MODEL = {
    AssistantContextualTool.SEARCH_SESSION_RECORDINGS: search_session_recordings,
}
CONTEXTUAL_TOOL_NAME_TO_TOOL_CONTEXT_PROMPT = {
    AssistantContextualTool.SEARCH_SESSION_RECORDINGS: """
Current recordings filters are:
{{{search_session_recordings_current_filters}}}
""".strip(),
}
CONTEXTUAL_TOOL_MODELS = tuple(CONTEXTUAL_TOOL_NAME_TO_TOOL_MODEL.values())


RootToolCall = create_and_query_insight | search_documentation | search_session_recordings
root_tools_parser = PydanticToolsParser(tools=[create_and_query_insight, search_documentation, *CONTEXTUAL_TOOL_MODELS])

RootMessageUnion = HumanMessage | AssistantMessage | FailureMessage | AssistantToolCallMessage

T = TypeVar("T", RootMessageUnion, BaseMessage)


class RootNode(AssistantNode):
    MAX_TOOL_CALLS = 4
    """
    Determines the maximum number of tool calls allowed in a single generation.
    """
    CONVERSATION_WINDOW_SIZE = 64000
    """
    Determines the maximum number of tokens allowed in the conversation window.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        history, new_window_id = self._construct_and_update_messages_window(state, config)

        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", ROOT_SYSTEM_PROMPT),
                    *[
                        (
                            "system",
                            f"<{tool_name}>\n{CONTEXTUAL_TOOL_NAME_TO_TOOL_CONTEXT_PROMPT.get(cast(AssistantContextualTool, tool_name), 'No context provided for this tool')}\n</{tool_name}>",
                        )
                        for tool_name in self._get_contextual_tools(config).keys()
                        if tool_name in CONTEXTUAL_TOOL_NAME_TO_TOOL_CONTEXT_PROMPT
                    ],
                ],
                template_format="mustache",
            )
            + history
        )
        chain = prompt | self._get_model(state, config)

        utc_now = datetime.datetime.now(datetime.UTC)
        project_now = utc_now.astimezone(self._team.timezone_info)

        message = chain.invoke(
            {
                "core_memory": self.core_memory_text,
                "utc_datetime_display": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_datetime_display": project_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_timezone": self._team.timezone_info.tzname(utc_now),
                **{
                    f"{tool_name}_{context_key}": context_value
                    for tool_name, context in self._get_contextual_tools(config).items()
                    for context_key, context_value in context.items()
                },
            },
            config,
        )
        message = cast(LangchainAIMessage, message)

        return PartialAssistantState(
            root_conversation_start_id=new_window_id,
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

    def _get_model(self, state: AssistantState, config: RunnableConfig):
        # Research suggests temperature is not _massively_ correlated with creativity, hence even in this very
        # conversational context we're using a temperature of 0, for near determinism (https://arxiv.org/html/2405.00492v1)
        base_model = ChatOpenAI(model="gpt-4o", temperature=0.0, streaming=True, stream_usage=True)

        # The agent can now be in loops. Since insight building is an expensive operation, we want to limit a recursion depth.
        # This will remove the functions, so the agent doesn't have any other option but to exit.
        if self._is_hard_limit_reached(state):
            return base_model

        available_tools: list[type[BaseModel]] = [create_and_query_insight]
        if settings.INKEEP_API_KEY:
            available_tools.append(search_documentation)
        for tool_name in self._get_contextual_tools(config).keys():
            if tool_name not in CONTEXTUAL_TOOL_NAME_TO_TOOL_MODEL:
                continue  # Possibly a deployment mismatch
            available_tools.append(CONTEXTUAL_TOOL_NAME_TO_TOOL_MODEL[cast(AssistantContextualTool, tool_name)])

        return base_model.bind_tools(available_tools, strict=True, parallel_tool_calls=False)

    def _get_assistant_messages_in_window(self, state: AssistantState) -> list[RootMessageUnion]:
        filtered_conversation = [message for message in state.messages if isinstance(message, RootMessageUnion)]
        if state.root_conversation_start_id is not None:
            filtered_conversation = self._get_conversation_window(
                filtered_conversation, state.root_conversation_start_id
            )
        return filtered_conversation

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        # Filter out messages that are not part of the conversation window.
        conversation_window = self._get_assistant_messages_in_window(state)

        # `assistant` messages must be contiguous with the respective `tool` messages.
        tool_result_messages = {
            message.tool_call_id: message
            for message in conversation_window
            if isinstance(message, AssistantToolCallMessage)
        }

        history: list[BaseMessage] = []
        for message in conversation_window:
            if isinstance(message, HumanMessage):
                history.append(LangchainHumanMessage(content=message.content, id=message.id))
            elif isinstance(message, AssistantMessage):
                # Filter out tool calls without a tool response, so the completion doesn't fail.
                tool_calls = [
                    tool for tool in (message.model_dump()["tool_calls"] or []) if tool["id"] in tool_result_messages
                ]

                history.append(LangchainAIMessage(content=message.content, tool_calls=tool_calls, id=message.id))

                # Append associated tool call messages.
                for tool_call in tool_calls:
                    tool_call_id = tool_call["id"]
                    result_message = tool_result_messages[tool_call_id]
                    history.append(
                        LangchainToolMessage(
                            content=result_message.content, tool_call_id=tool_call_id, id=result_message.id
                        )
                    )
            elif isinstance(message, FailureMessage):
                history.append(
                    LangchainAIMessage(content=message.content or "An unknown failure occurred.", id=message.id)
                )

        return history

    def _construct_and_update_messages_window(
        self, state: AssistantState, config: RunnableConfig
    ) -> tuple[list[BaseMessage], str | None]:
        """
        Retrieves the current conversation window, finds a new window if necessary, and enforces the tool call limit.
        """

        history = self._construct_messages(state)

        # Find a new window id and trim the history to it.
        new_window_id = self._find_new_window_id(state, config, history)
        if new_window_id is not None:
            history = self._get_conversation_window(history, new_window_id)

        # Force the agent to stop if the tool call limit is reached.
        if self._is_hard_limit_reached(state):
            history.append(LangchainHumanMessage(content=ROOT_HARD_LIMIT_REACHED_PROMPT))

        return history, new_window_id

    def _is_hard_limit_reached(self, state: AssistantState) -> bool:
        return state.root_tool_calls_count is not None and state.root_tool_calls_count >= self.MAX_TOOL_CALLS

    def _find_new_window_id(
        self, state: AssistantState, config: RunnableConfig, window: list[BaseMessage]
    ) -> str | None:
        """
        If we simply trim the conversation on N tokens, the cache will be invalidated for every new message after that
        limit leading to increased latency. Instead, when we hit the limit, we trim the conversation to N/2 tokens, so
        the cache invalidates only for the next generation.
        """
        model = self._get_model(state, config)

        if model.get_num_tokens_from_messages(window) > self.CONVERSATION_WINDOW_SIZE:
            trimmed_window: list[BaseMessage] = trim_messages(
                window,
                token_counter=model,
                max_tokens=math.floor(self.CONVERSATION_WINDOW_SIZE / 2),
                start_on="human",
                end_on=("human", "tool"),
                allow_partial=False,
            )
            if len(trimmed_window) != len(window):
                if trimmed_window:
                    new_start_id = trimmed_window[0].id
                    return new_start_id
                # We don't want the conversation to be completely empty.
                if isinstance(window[-1], LangchainHumanMessage):
                    return window[-1].id
                if len(window) > 1 and isinstance(window[-2], LangchainAIMessage):
                    return window[-2].id
        return None

    def _get_conversation_window(self, messages: list[T], start_id: str) -> list[T]:
        for idx, message in enumerate(messages):
            if message.id == start_id:
                return messages[idx:]
        return messages


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
        else:
            return PartialAssistantState(
                root_tool_call_id=langchain_msg.tool_calls[-1]["id"],
                root_tool_insight_plan=None,  # No insight plan here
                root_tool_insight_type=None,  # No insight type here
                root_tool_calls_count=tool_call_count + 1,
            )

    def router(self, state: AssistantState) -> RouteName:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantToolCallMessage):
            return "root"
        if state.root_tool_call_id:
            if state.root_tool_insight_type:
                return "insights"
            # For all other tools, we route based on tool name
            return cast(RouteName, self._get_tool_call(state.messages, state.root_tool_call_id).name)
        return "end"

    def _construct_langchain_ai_message(self, message: AssistantMessage):
        return LangchainAIMessage(content=message.content, tool_calls=message.model_dump()["tool_calls"] or [])
