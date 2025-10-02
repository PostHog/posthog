import json
import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, Optional, TypeVar, Union, cast
from uuid import uuid4

import posthoganalytics
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeInterrupt
from posthoganalytics import capture_exception
from pydantic import BaseModel

from posthog.schema import (
    AssistantContextualTool,
    AssistantMessage,
    AssistantToolCallMessage,
    ContextMessage,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
)

from posthog.models.organization import OrganizationMembership
from posthog.sync import database_sync_to_async

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.conversation_summarizer.nodes import AnthropicConversationSummarizer
from ee.hogai.graph.root.tools.todo_write import TodoWriteTool
from ee.hogai.graph.shared_prompts import CORE_MEMORY_PROMPT
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL
from ee.hogai.utils.anthropic import add_cache_control, convert_to_anthropic_messages, normalize_ai_anthropic_message
from ee.hogai.utils.helpers import find_start_message, insert_messages_before_start
from ee.hogai.utils.types import (
    AssistantMessageUnion,
    AssistantNodeName,
    AssistantState,
    BaseState,
    BaseStateWithMessages,
    InsightQuery,
    PartialAssistantState,
    ReplaceMessages,
)
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    ROOT_BILLING_CONTEXT_ERROR_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT,
    ROOT_CONVERSATION_SUMMARY_PROMPT,
    ROOT_HARD_LIMIT_REACHED_PROMPT,
    ROOT_SYSTEM_PROMPT,
)
from .tools import (
    ReadDataTool,
    ReadTaxonomyTool,
    SearchTool,
    create_and_query_insight,
    create_dashboard,
    session_summarization,
)

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool

SLASH_COMMAND_INIT = "/init"
SLASH_COMMAND_REMEMBER = "/remember"

RouteName = Literal[
    "insights",
    "root",
    "end",
    "search_documentation",
    "memory_onboarding",
    "insights_search",
    "billing",
    "session_summarization",
    "create_dashboard",
]


RootMessageUnion = HumanMessage | AssistantMessage | FailureMessage | AssistantToolCallMessage | ContextMessage
T = TypeVar("T", RootMessageUnion, BaseMessage)

RootTool = Union[type[BaseModel], "MaxTool"]


class RootNode(AssistantNode):
    MAX_TOOL_CALLS = 24
    """
    Determines the maximum number of tool calls allowed in a single generation.
    """
    CONVERSATION_WINDOW_SIZE = 64000
    """
    Determines the maximum number of tokens allowed in the conversation window.
    """
    THINKING_CONFIG = {"type": "enabled", "budget_tokens": 1024}
    """
    Determines the thinking configuration for the model.
    """

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        # Add context messages on start of the conversation.
        tools, billing_context_prompt, core_memory = await asyncio.gather(
            self._get_tools(state, config),
            self._get_billing_prompt(config),
            self._aget_core_memory_text(),
        )

        # Add context messages on start of the conversation.
        messages_to_replace: Sequence[AssistantMessageUnion] = []
        if self._is_first_turn(state) and (
            updated_messages := await self.context_manager.aget_state_messages_with_context(state)
        ):
            # Check if context was actually added by comparing lengths
            messages_to_replace = updated_messages

        # Calculate the initial window.
        langchain_messages = self._construct_messages(
            messages_to_replace or state.messages, state.root_conversation_start_id, state.root_tool_calls_count
        )
        window_id = state.root_conversation_start_id

        # Summarize the conversation if it's too long.
        if await self._should_summarize_conversation(state, tools, langchain_messages):
            # Exclude the last message if it's the first turn.
            messages_to_summarize = langchain_messages[:-1] if self._is_first_turn(state) else langchain_messages
            summary = await AnthropicConversationSummarizer(self._team, self._user).summarize(messages_to_summarize)
            summary_message = ContextMessage(
                content=ROOT_CONVERSATION_SUMMARY_PROMPT.format(summary=summary),
                id=str(uuid4()),
            )

            # Insert the summary message before the last human message
            messages_to_replace = insert_messages_before_start(
                messages_to_replace or state.messages, [summary_message], start_id=state.start_id
            )

            # Update window
            window_id = self._find_new_window_id(messages_to_replace)
            langchain_messages = self._construct_messages(messages_to_replace, window_id, state.root_tool_calls_count)

        core_memory_prompt = (
            PromptTemplate.from_template(CORE_MEMORY_PROMPT, template_format="mustache")
            .format_prompt(core_memory=core_memory)
            .to_string()
        )

        system_prompts = ChatPromptTemplate.from_messages(
            [
                ("system", ROOT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        ).format_messages(
            core_memory_prompt=core_memory_prompt,
            billing_context=billing_context_prompt,
        )

        # Mark the longest default prefix as cacheable
        add_cache_control(system_prompts[-1])

        message = await self._get_model(state, tools).ainvoke(system_prompts + langchain_messages, config)
        assistant_message = normalize_ai_anthropic_message(message)

        new_messages: list[AssistantMessageUnion] = [assistant_message]
        # Replace the messages with the new message window
        if messages_to_replace:
            new_messages = ReplaceMessages([*messages_to_replace, assistant_message])

        return PartialAssistantState(root_conversation_start_id=window_id, messages=new_messages)

    async def get_reasoning_message(
        self, input: BaseState, default_message: Optional[str] = None
    ) -> ReasoningMessage | None:
        input = cast(AssistantState, input)
        if self.context_manager.has_awaitable_context(input):
            return ReasoningMessage(content="Calculating context")
        return None

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT

    def _find_new_window_id(
        self, messages: list[AssistantMessageUnion], max_messages: int = 10, max_tokens: int = 1000
    ) -> str:
        new_window_id: str = cast(str, messages[-1].id)
        for message in reversed(messages):
            if message.id is not None:
                if isinstance(message, HumanMessage):
                    new_window_id = message.id
                if isinstance(message, AssistantMessage):
                    new_window_id = message.id

            max_messages -= 1
            max_tokens -= self._get_estimated_tokens(message)
            if max_messages <= 0 or max_tokens <= 0:
                break

        return new_window_id

    def _get_estimated_tokens(self, message: AssistantMessageUnion) -> int:
        char_count = 0
        if isinstance(message, HumanMessage):
            char_count = len(message.content)
        if isinstance(message, AssistantMessage):
            char_count = len(message.content) + sum(len(json.dumps(m.args)) for m in message.tool_calls or [])
        if isinstance(message, AssistantToolCallMessage):
            char_count = len(message.content)
        return round(char_count / 4)

    def _is_first_turn(self, state: AssistantState) -> bool:
        last_message = state.messages[-1]
        if isinstance(last_message, HumanMessage):
            return last_message == find_start_message(state.messages, start_id=state.start_id)
        return False

    def _has_session_summarization_feature_flag(self) -> bool:
        """
        Check if the user has the session summarization feature flag enabled.
        """
        return posthoganalytics.feature_enabled(
            "max-session-summarization",
            str(self._user.distinct_id),
            groups={"organization": str(self._team.organization_id)},
            group_properties={"organization": {"id": str(self._team.organization_id)}},
            send_feature_flag_events=False,
        )

    @database_sync_to_async
    def _check_user_has_billing_access(self) -> bool:
        """
        Check if the user has access to the billing tool.
        """
        return self._user.organization_memberships.get(organization=self._team.organization).level in (
            OrganizationMembership.Level.ADMIN,
            OrganizationMembership.Level.OWNER,
        )

    def _check_user_has_billing_context(self, config: RunnableConfig) -> bool:
        return self.context_manager.get_billing_context() is not None

    async def _get_billing_prompt(self, config: RunnableConfig) -> str:
        """Get billing information including whether to include the billing tool and the prompt.
        Returns:
            str: prompt
        """
        has_billing_context = self._check_user_has_billing_context(config)
        has_access = await self._check_user_has_billing_access()

        if has_access and not has_billing_context:
            return ROOT_BILLING_CONTEXT_ERROR_PROMPT

        prompt = (
            ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT
            if has_access and has_billing_context
            else ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT
        )
        return prompt

    def _get_model(self, state: AssistantState, tools: list[RootTool]):
        base_model = MaxChatAnthropic(
            model="claude-sonnet-4-5",
            streaming=True,
            stream_usage=True,
            user=self._user,
            team=self._team,
            betas=["interleaved-thinking-2025-05-14"],
            max_tokens=8192,
            thinking=self.THINKING_CONFIG,
            conversation_start_dt=state.start_dt,
        )

        # The agent can operate in loops. Since insight building is an expensive operation, we want to limit a recursion depth.
        # This will remove the functions, so the agent doesn't have any other option but to exit.
        if self._is_hard_limit_reached(state.root_tool_calls_count):
            return base_model

        return base_model.bind_tools(tools, parallel_tool_calls=False)

    async def _get_tools(self, state: AssistantState, config: RunnableConfig) -> list[RootTool]:
        from ee.hogai.tool import MaxTool, get_contextual_tool_class

        available_tools: list[type[BaseModel] | MaxTool] = []

        # Add the basic toolkit
        toolkit = (ReadTaxonomyTool, SearchTool, TodoWriteTool)
        for StaticMaxToolClass in toolkit:
            available_tools.append(StaticMaxToolClass(team=self._team, user=self._user, state=state, config=config))

        # Dynamically initialize some tools based on conditions
        dynamic_tools = await asyncio.gather(
            ReadDataTool.create_tool_class(team=self._team, user=self._user, state=state, config=config)
        )
        available_tools.extend(dynamic_tools)

        tool_names = self.context_manager.get_contextual_tools().keys()
        is_editing_insight = AssistantContextualTool.CREATE_AND_QUERY_INSIGHT in tool_names
        if not is_editing_insight:
            # This is the default tool, which can be overriden by the MaxTool based tool with the same name
            available_tools.append(create_and_query_insight)

        # Check if session summarization is enabled for the user
        if self._has_session_summarization_feature_flag():
            available_tools.append(session_summarization)

        available_tools.append(create_dashboard)

        # Inject contextual tools
        for tool_name in tool_names:
            ContextualMaxToolClass = get_contextual_tool_class(tool_name)
            if ContextualMaxToolClass is None:
                continue  # Ignoring a tool that the backend doesn't know about - might be a deployment mismatch
            available_tools.append(ContextualMaxToolClass(team=self._team, user=self._user, state=state, config=config))

        return available_tools

    def _construct_messages(
        self,
        messages: Sequence[AssistantMessageUnion],
        window_start_id: str | None = None,
        tool_calls_count: int | None = None,
    ) -> list[BaseMessage]:
        # Filter out messages that are not part of the conversation window.
        conversation_window = self._get_assistant_messages_in_window(messages, window_start_id)

        # `assistant` messages must be contiguous with the respective `tool` messages.
        tool_result_messages = {
            message.tool_call_id: message
            for message in conversation_window
            if isinstance(message, AssistantToolCallMessage)
        }

        history: list[BaseMessage] = convert_to_anthropic_messages(conversation_window, tool_result_messages)

        # Force the agent to stop if the tool call limit is reached.
        if self._is_hard_limit_reached(tool_calls_count):
            history.append(LangchainHumanMessage(content=ROOT_HARD_LIMIT_REACHED_PROMPT))

        # Append a single cache control to the last human message or last tool message,
        # so we cache the full prefix of the conversation.
        for i in range(len(history) - 1, -1, -1):
            maybe_content_arr = history[i].content
            if (
                isinstance(history[i], LangchainHumanMessage | LangchainAIMessage)
                and isinstance(maybe_content_arr, list)
                and len(maybe_content_arr) > 0
                and isinstance(maybe_content_arr[-1], dict)
            ):
                maybe_content_arr[-1]["cache_control"] = {"type": "ephemeral"}
                break

        return history

    def _get_assistant_messages_in_window(
        self, messages: Sequence[AssistantMessageUnion], window_start_id: str | None = None
    ) -> list[RootMessageUnion]:
        filtered_conversation = [message for message in messages if isinstance(message, RootMessageUnion)]
        if window_start_id is not None:
            filtered_conversation = self._get_conversation_window(filtered_conversation, window_start_id)
        return filtered_conversation

    def _is_hard_limit_reached(self, tool_calls_count: int | None) -> bool:
        return tool_calls_count is not None and tool_calls_count >= self.MAX_TOOL_CALLS

    async def _should_summarize_conversation(
        self, state: AssistantState, tools: list[RootTool], messages: list[BaseMessage]
    ) -> bool:
        # Avoid summarizing the conversation if there is only two human messages.
        human_messages = [message for message in messages if isinstance(message, LangchainHumanMessage)]
        if len(human_messages) <= 2:
            return False

        token_count = await self._get_token_count(state, messages, tools)
        return token_count > self.CONVERSATION_WINDOW_SIZE

    async def _get_token_count(self, state: AssistantState, messages: list[BaseMessage], tools: list[RootTool]) -> int:
        # Contains an async method in get_num_tokens_from_messages
        model = self._get_model(state, tools)
        return await database_sync_to_async(model.get_num_tokens_from_messages, thread_sensitive=False)(
            messages, thinking=self.THINKING_CONFIG
        )

    def _get_conversation_window(self, messages: list[T], start_id: str) -> list[T]:
        for idx, message in enumerate(messages):
            if message.id == start_id:
                return messages[idx:]
        return messages


class RootNodeTools(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT_TOOLS

    async def get_reasoning_message(
        self, input: BaseState, default_message: Optional[str] = None
    ) -> ReasoningMessage | None:
        if not isinstance(input, BaseStateWithMessages):
            return None
        if not input.messages:
            return None

        assert isinstance(input.messages[-1], AssistantMessage)
        tool_calls = input.messages[-1].tool_calls or []
        assert len(tool_calls) <= 1
        if len(tool_calls) == 0:
            return None
        tool_call = tool_calls[0]
        content = None
        if tool_call.name == "create_and_query_insight":
            content = "Coming up with an insight"
        else:
            # This tool should be in CONTEXTUAL_TOOL_NAME_TO_TOOL, but it might not be in the rare case
            # when the tool has been removed from the backend since the user's frontend was loaded
            ToolClass = CONTEXTUAL_TOOL_NAME_TO_TOOL.get(tool_call.name)  # type: ignore
            content = (
                ToolClass(team=self._team, user=self._user).thinking_message
                if ToolClass
                else f"Running tool {tool_call.name}"
            )

        return ReasoningMessage(content=content) if content else None

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage) or not last_message.tool_calls:
            # Reset tools.
            return PartialAssistantState(root_tool_calls_count=0)

        tool_call_count = state.root_tool_calls_count or 0

        tools_calls = last_message.tool_calls
        if len(tools_calls) != 1:
            raise ValueError("Expected exactly one tool call.")

        tool_names = self.context_manager.get_contextual_tools().keys()
        is_editing_insight = AssistantContextualTool.CREATE_AND_QUERY_INSIGHT in tool_names
        tool_call = tools_calls[0]

        from ee.hogai.tool import get_contextual_tool_class

        if tool_call.name == "create_and_query_insight" and not is_editing_insight:
            return PartialAssistantState(
                root_tool_call_id=tool_call.id,
                root_tool_insight_plan=tool_call.args["query_description"],
                root_tool_calls_count=tool_call_count + 1,
            )
        elif tool_call.name == "session_summarization":
            return PartialAssistantState(
                root_tool_call_id=tool_call.id,
                session_summarization_query=tool_call.args["session_summarization_query"],
                # Safety net in case the argument is missing to avoid raising exceptions internally
                should_use_current_filters=tool_call.args.get("should_use_current_filters", False),
                summary_title=tool_call.args.get("summary_title"),
                root_tool_calls_count=tool_call_count + 1,
            )
        elif tool_call.name == "create_dashboard":
            raw_queries = tool_call.args["search_insights_queries"]
            search_insights_queries = [InsightQuery.model_validate(query) for query in raw_queries]

            return PartialAssistantState(
                root_tool_call_id=tool_call.id,
                dashboard_name=tool_call.args.get("dashboard_name"),
                search_insights_queries=search_insights_queries,
                root_tool_calls_count=tool_call_count + 1,
            )
        elif ToolClass := get_contextual_tool_class(tool_call.name):
            tool_class = ToolClass(team=self._team, user=self._user, state=state)
            try:
                result = await tool_class.ainvoke(tool_call.model_dump(), config)
            except Exception as e:
                capture_exception(
                    e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
                )
                result = AssistantToolCallMessage(
                    content="The tool raised an internal error. Do not immediately retry the tool call and explain to the user what happened. If the user asks you to retry, you are allowed to do that.",
                    id=str(uuid4()),
                    tool_call_id=tool_call.id,
                    visible=False,
                )
            if not isinstance(result, LangchainToolMessage | AssistantToolCallMessage):
                raise TypeError(f"Expected a {LangchainToolMessage} or {AssistantToolCallMessage}, got {type(result)}")

            # Handle the basic toolkit
            if (
                isinstance(result, LangchainToolMessage)
                and result.name == "Search"
                and isinstance(result.artifact, dict)
            ):
                match result.artifact.get("kind"):
                    case "insights":
                        return PartialAssistantState(
                            root_tool_call_id=tool_call.id,
                            search_insights_query=result.artifact.get("query"),
                            root_tool_calls_count=tool_call_count + 1,
                        )
                    case "docs":
                        return PartialAssistantState(
                            root_tool_call_id=tool_call.id,
                            root_tool_calls_count=tool_call_count + 1,
                        )

            if (
                isinstance(result, LangchainToolMessage)
                and result.name == "ReadData"
                and isinstance(result.artifact, dict)
                and result.artifact.get("kind") == "billing_info"
            ):
                return PartialAssistantState(
                    root_tool_call_id=tool_call.id,
                    root_tool_calls_count=tool_call_count + 1,
                )

            # If this is a navigation tool call, pause the graph execution
            # so that the frontend can re-initialise Max with a new set of contextual tools.
            if tool_call.name == "navigate" and not isinstance(result, AssistantToolCallMessage):
                navigate_message = AssistantToolCallMessage(
                    content=str(result.content) if result.content else "",
                    ui_payload={tool_call.name: result.artifact},
                    id=str(uuid4()),
                    tool_call_id=tool_call.id,
                    visible=True,
                )
                # Raising a `NodeInterrupt` ensures the assistant graph stops here and
                # surfaces the navigation confirmation to the client. The next user
                # interaction will resume the graph with potentially different
                # contextual tools.
                raise NodeInterrupt(navigate_message)

            new_state = tool_class._state  # latest state, in case the tool has updated it
            last_message = new_state.messages[-1]
            if isinstance(last_message, AssistantToolCallMessage) and last_message.tool_call_id == tool_call.id:
                return PartialAssistantState(
                    # we send all messages from the tool call onwards
                    messages=new_state.messages[len(state.messages) :],
                    root_tool_calls_count=tool_call_count + 1,
                )

            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=str(result.content) if result.content else "",
                        ui_payload={tool_call.name: result.artifact},
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                        visible=tool_class.show_tool_call_message,
                    )
                    if not isinstance(result, AssistantToolCallMessage)
                    else result
                ],
                root_tool_calls_count=tool_call_count + 1,
            )
        else:
            raise ValueError(f"Unknown tool called: {tool_call.name}")

    def router(self, state: AssistantState) -> RouteName:
        last_message = state.messages[-1]

        if isinstance(last_message, AssistantToolCallMessage):
            return "root"  # Let the root either proceed or finish, since it now can see the tool call result
        if isinstance(last_message, AssistantMessage) and state.root_tool_call_id:
            tool_calls = getattr(last_message, "tool_calls", None)
            if tool_calls and len(tool_calls) > 0:
                tool_call = tool_calls[0]
                tool_call_name = tool_call.name
                if tool_call_name == "ReadData" and tool_call.args.get("kind") == "billing_info":
                    return "billing"
                if tool_call_name == "create_dashboard":
                    return "create_dashboard"
            if state.root_tool_insight_plan:
                return "insights"
            elif state.search_insights_query:
                return "insights_search"
            elif state.session_summarization_query:
                return "session_summarization"
            else:
                return "search_documentation"
        return "end"
