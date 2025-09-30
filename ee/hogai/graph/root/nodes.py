import re
import json
import math
import asyncio
from collections.abc import Sequence
from typing import Any, Literal, Optional, TypeVar, cast
from uuid import uuid4

from django.conf import settings

import posthoganalytics
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    trim_messages,
)
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeInterrupt
from posthoganalytics import capture_exception

from posthog.schema import (
    AssistantMessage,
    AssistantTool,
    AssistantToolCallMessage,
    ContextMessage,
    FailureMessage,
    HumanMessage,
    MultiVisualizationMessage,
    ReasoningMessage,
    ToolExecutionStatus,
    VisualizationItem,
    VisualizationMessage,
)

from posthog.models.organization import OrganizationMembership
from posthog.sync import database_sync_to_async

from products.product_analytics.backend.max_tools import EditCurrentInsightTool

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.shared_prompts import CORE_MEMORY_PROMPT
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.tool import MaxTool, ParallelToolExecution
from ee.hogai.utils.anthropic import (
    add_cache_control,
    get_thinking_from_assistant_message,
    normalize_ai_anthropic_message,
)
from ee.hogai.utils.types import (
    AssistantMessageUnion,
    AssistantNodeName,
    AssistantState,
    BaseState,
    PartialAssistantState,
    ReplaceMessages,
)
from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery, InsightArtifact
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    MAX_PERSONALITY_PROMPT,
    ROOT_BILLING_CONTEXT_ERROR_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT,
    ROOT_HARD_LIMIT_REACHED_PROMPT,
    ROOT_SYSTEM_PROMPT,
    SESSION_SUMMARIZATION_PROMPT_BASE,
    SESSION_SUMMARIZATION_PROMPT_NO_REPLAY_CONTEXT,
    SESSION_SUMMARIZATION_PROMPT_WITH_REPLAY_CONTEXT,
)

SLASH_COMMAND_INIT = "/init"
SLASH_COMMAND_REMEMBER = "/remember"

RouteName = Literal[
    "root",
    "end",
    "memory_onboarding",
]


RootMessageUnion = HumanMessage | AssistantMessage | FailureMessage | AssistantToolCallMessage | ContextMessage
T = TypeVar("T", RootMessageUnion, BaseMessage)


class RootNode(AssistantNode):
    MAX_TOOL_CALLS = 4
    """
    Determines the maximum number of tool calls allowed in a single generation.
    """
    CONVERSATION_WINDOW_SIZE = 64000

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT

    """
    Determines the maximum number of tokens allowed in the conversation window.
    """
    THINKING_CONFIG = {"type": "enabled", "budget_tokens": 1024}
    """
    Determines the thinking configuration for the model.
    """

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        # Add context messages on start of the conversation.
        updated_messages: Sequence[AssistantMessageUnion] = []
        messages_changed = False
        if self._is_first_turn(state) and (
            updated_messages := await self.context_manager.aget_state_messages_with_context(state)
        ):
            # Check if context was actually added by comparing lengths
            messages_changed = len(updated_messages) != len(state.messages)
            state.messages = updated_messages

        message_window, billing_context, core_memory = await asyncio.gather(
            self._construct_and_update_messages_window(state, config),
            self._get_billing_info(config),
            self._aget_core_memory_text(),
        )
        should_add_billing_tool, billing_context_prompt = billing_context
        history, new_window_id = message_window

        # Build system prompt with conditional session summarization and insight search sections
        system_prompt_template = ROOT_SYSTEM_PROMPT
        # Check if session summarization is enabled for the user
        session_summarization_context = ""
        if self._has_session_summarization_feature_flag():
            context = self._render_session_summarization_context(config)
            # Inject session summarization context
            session_summarization_context = context
        system_prompt_template = re.sub(
            r"\n?<session_summarization>.*?</session_summarization>",
            session_summarization_context,
            system_prompt_template,
            flags=re.DOTALL,
        )
        # Check if insight search is enabled for the user
        if not self._has_insight_search_feature_flag():
            # Remove the reference to search_insights in basic_functionality
            system_prompt_template = re.sub(r"\n?\d+\. `search_insights`.*?[^\n]*", "", system_prompt_template)
            # Remove the insight_search section from prompt using regex
            system_prompt_template = re.sub(
                r"\n?<insight_search>.*?</insight_search>", "", system_prompt_template, flags=re.DOTALL
            )
            # Remove the CRITICAL ROUTING LOGIC section when insight search is disabled
            system_prompt_template = re.sub(
                r"\n?CRITICAL ROUTING LOGIC:.*?(?=Follow these guidelines when retrieving data:)",
                "",
                system_prompt_template,
                flags=re.DOTALL,
            )

        system_prompts = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt_template),
            ],
            template_format="mustache",
        ).format_messages(
            personality_prompt=MAX_PERSONALITY_PROMPT,
            core_memory_prompt=CORE_MEMORY_PROMPT,
            core_memory=core_memory,
            billing_context=billing_context_prompt,
        )

        # Mark the longest default prefix as cacheable
        add_cache_control(system_prompts[-1])

        message = await self._get_model(
            state,
            config,
            extra_tools=["retrieve_billing_information"] if should_add_billing_tool else [],
        ).ainvoke(
            system_prompts + history,
            config,
        )
        assistant_message = normalize_ai_anthropic_message(message)

        return PartialAssistantState(
            root_conversation_start_id=new_window_id,
            messages=ReplaceMessages([*updated_messages, assistant_message])
            if messages_changed
            else [assistant_message],
        )

    async def get_reasoning_message(
        self, input: BaseState, default_message: Optional[str] = None
    ) -> ReasoningMessage | None:
        input = cast(AssistantState, input)
        if self.context_manager.has_awaitable_context(input):
            return ReasoningMessage(content="Calculating context")
        return None

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

    def _has_insight_search_feature_flag(self) -> bool:
        """
        Check if the user has the insight search feature flag enabled.
        """
        return posthoganalytics.feature_enabled(
            "max-ai-insight-search",
            str(self._user.distinct_id),
            groups={"organization": str(self._team.organization_id)},
            group_properties={"organization": {"id": str(self._team.organization_id)}},
            send_feature_flag_events=False,
        )

    @database_sync_to_async
    def _get_billing_info(self, config: RunnableConfig) -> tuple[bool, str]:
        """Get billing information including whether to include the billing tool and the prompt.
        Returns:
            Tuple[bool, str]: (should_add_billing_tool, prompt)
        """
        has_billing_context = self._get_billing_context(config) is not None

        has_access = self._user.organization_memberships.get(organization=self._team.organization).level in (
            OrganizationMembership.Level.ADMIN,
            OrganizationMembership.Level.OWNER,
        )
        if has_access and not has_billing_context:
            return False, ROOT_BILLING_CONTEXT_ERROR_PROMPT

        prompt = (
            ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT
            if has_access and has_billing_context
            else ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT
        )

        should_add_billing_tool = has_access and has_billing_context

        return should_add_billing_tool, prompt

    def _get_model(self, state: AssistantState, config: RunnableConfig, extra_tools: list[str] | None = None):
        if extra_tools is None:
            extra_tools = []

        base_model = MaxChatAnthropic(
            model_name="claude-sonnet-4-0",
            streaming=True,
            stream_usage=True,
            user=self._user,
            team=self._team,
            betas=["interleaved-thinking-2025-05-14"],
            max_tokens_to_sample=8192,
            thinking=self.THINKING_CONFIG,
            conversation_start_dt=state.start_dt,
            stop=None,
            timeout=None,
        )

        # The agent can operate in loops. Since insight building is an expensive operation, we want to limit a recursion depth.
        # This will remove the functions, so the agent doesn't have any other option but to exit.
        if self._is_hard_limit_reached(state):
            return base_model

        from ee.hogai.graph.billing.tool import RetrieveBillingInformationTool
        from ee.hogai.graph.dashboards.tool import CreateDashboardTool
        from ee.hogai.graph.query_planner.tool import CreateInsightTool
        from ee.hogai.tool import get_assistant_tool_class

        available_tools: list[type[MaxTool]] = []
        # Check if insight search is enabled for the user
        if self._has_insight_search_feature_flag():
            from ee.hogai.graph.insights.tool import SearchInsightsTool

            available_tools.append(SearchInsightsTool)
        # Check if session summarization is enabled for the user
        if self._has_session_summarization_feature_flag():
            from ee.hogai.graph.session_summaries.tool import SessionSummarizationTool

            available_tools.append(SessionSummarizationTool)
        # Add dashboard creation tool (always available)
        available_tools.append(CreateDashboardTool)
        if settings.INKEEP_API_KEY:
            from ee.hogai.graph.inkeep_docs.tool import SearchDocumentationTool

            available_tools.append(SearchDocumentationTool)
        tool_names = self.context_manager.get_contextual_tools().keys()
        is_editing_insight = AssistantTool.CREATE_AND_QUERY_INSIGHT in tool_names
        if not is_editing_insight:
            # This is the default tool, which can be overriden by the MaxTool based tool with the same name
            available_tools.append(CreateInsightTool)
        else:
            available_tools.append(EditCurrentInsightTool)
        for tool_name in tool_names:
            ToolClass = get_assistant_tool_class(tool_name)
            if ToolClass is None:
                continue  # Ignoring a tool that the backend doesn't know about - might be a deployment mismatch
            available_tools.append(ToolClass)  # type: ignore

        if "retrieve_billing_information" in extra_tools:
            from ee.hogai.graph.billing.tool import RetrieveBillingInformationTool

            available_tools.append(RetrieveBillingInformationTool)

        tool_functions = [
            tool(team=self._team, user=self._user).get_tool_function_description() for tool in available_tools
        ]
        return base_model.bind_tools(tool_functions, parallel_tool_calls=True)

    def _get_assistant_messages_in_window(self, state: AssistantState) -> list[RootMessageUnion]:
        filtered_conversation = [message for message in state.messages if isinstance(message, RootMessageUnion)]
        if state.root_conversation_start_id is not None:
            filtered_conversation = self._get_conversation_window(
                filtered_conversation, state.root_conversation_start_id
            )
        return filtered_conversation

    async def _construct_and_update_messages_window(
        self, state: AssistantState, config: RunnableConfig
    ) -> tuple[list[BaseMessage], str | None]:
        """
        Retrieves the current conversation window, finds a new window if necessary, and enforces the tool call limit.
        """

        history = self._construct_messages(state)

        # Find a new window id and trim the history to it.
        new_window_id = await self._find_new_window_id(state, config, history)
        if new_window_id is not None:
            history = self._get_conversation_window(history, new_window_id)

        # Force the agent to stop if the tool call limit is reached.
        if self._is_hard_limit_reached(state):
            history.append(LangchainHumanMessage(content=ROOT_HARD_LIMIT_REACHED_PROMPT))

        return history, new_window_id

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
            if isinstance(message, HumanMessage) or isinstance(message, ContextMessage):
                history.append(LangchainHumanMessage(content=[{"type": "text", "text": message.content}]))
            elif isinstance(message, AssistantMessage):
                content = get_thinking_from_assistant_message(message)
                if message.content:
                    content.append({"type": "text", "text": message.content})

                # Filter out tool calls without a tool response, so the completion doesn't fail.
                tool_calls = [
                    tool for tool in (message.model_dump()["tool_calls"] or []) if tool["id"] in tool_result_messages
                ]

                if content or tool_calls:
                    history.append(
                        LangchainAIMessage(
                            content=cast(list[str | dict[str, Any]], content),
                            tool_calls=tool_calls,
                        )
                    )

                # Append associated tool call messages.
                for tool_call in tool_calls:
                    tool_call_id = tool_call["id"]
                    result_message = tool_result_messages[tool_call_id]
                    history.append(
                        LangchainHumanMessage(
                            content=[
                                {"type": "tool_result", "tool_use_id": tool_call_id, "content": result_message.content}
                            ],
                        ),
                    )
            elif isinstance(message, FailureMessage):
                history.append(
                    LangchainHumanMessage(
                        content=[{"type": "text", "text": message.content or "An unknown failure occurred."}],
                    )
                )

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

    def _is_hard_limit_reached(self, state: AssistantState) -> bool:
        return state.root_tool_calls_count is not None and state.root_tool_calls_count >= self.MAX_TOOL_CALLS

    async def _find_new_window_id(
        self, state: AssistantState, config: RunnableConfig, window: list[BaseMessage]
    ) -> str | None:
        """
        If we simply trim the conversation on N tokens, the cache will be invalidated for every new message after that
        limit leading to increased latency. Instead, when we hit the limit, we trim the conversation to N/2 tokens, so
        the cache invalidates only for the next generation.
        """
        model = self._get_model(state, config)

        # Quickly skip the window check if there are less than 3 human messages.
        human_messages = [message for message in window if isinstance(message, LangchainHumanMessage)]
        if len(human_messages) < 3:
            return None

        if await self._has_reached_token_limit(model, window):
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

    async def _has_reached_token_limit(self, model: Any, window: list[BaseMessage]) -> bool:
        # Contains an async method in get_num_tokens_from_messages
        token_count = await database_sync_to_async(model.get_num_tokens_from_messages, thread_sensitive=False)(
            window, thinking=self.THINKING_CONFIG
        )
        return token_count > self.CONVERSATION_WINDOW_SIZE

    def _get_conversation_window(self, messages: list[T], start_id: str) -> list[T]:
        for idx, message in enumerate(messages):
            if message.id == start_id:
                return messages[idx:]
        return messages

    def _render_session_summarization_context(self, config: RunnableConfig) -> str:
        """Render the user context template with the provided context strings."""
        search_session_recordings_context = self.context_manager.get_contextual_tools().get("search_session_recordings")
        if (
            not search_session_recordings_context
            or not isinstance(search_session_recordings_context, dict)
            or not search_session_recordings_context.get("current_filters")
            or not isinstance(search_session_recordings_context["current_filters"], dict)
        ):
            conditional_context = SESSION_SUMMARIZATION_PROMPT_NO_REPLAY_CONTEXT
        else:
            current_filters = search_session_recordings_context["current_filters"]
            conditional_template = PromptTemplate.from_template(
                SESSION_SUMMARIZATION_PROMPT_WITH_REPLAY_CONTEXT, template_format="mustache"
            )
            conditional_context = conditional_template.format_prompt(
                current_filters=json.dumps(current_filters)
            ).to_string()
        template = PromptTemplate.from_template(SESSION_SUMMARIZATION_PROMPT_BASE, template_format="mustache")
        return template.format_prompt(conditional_context=conditional_context).to_string()


class RootNodeTools(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT_TOOLS

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage) or not last_message.tool_calls:
            # Reset tools.
            return PartialAssistantState(root_tool_calls_count=0)

        tool_call_count = state.root_tool_calls_count or 0

        tool_calls = last_message.tool_calls

        navigate_tool_call = next((tool_call for tool_call in tool_calls if tool_call.name == "navigate"), None)
        if navigate_tool_call and len(tool_calls) > 1:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="Do not use the navigate tool in combination with other tools. First navigate, then use the tools on the new page.",
                        id=str(uuid4()),
                        tool_call_id=navigate_tool_call.id,
                        visible=False,
                    )
                ],
                root_tool_calls_count=tool_call_count + 1,
            )

        result_messages: list[AssistantMessageUnion] = []

        ToolExecutionClass = ParallelToolExecution(
            team=self._team, user=self._user, write_message_afunc=self._write_message
        )
        try:
            tool_results, tool_execution_message = await ToolExecutionClass.arun(tool_calls, state, config)
        except Exception as e:
            capture_exception(
                e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
            )
            result_messages.extend(
                [
                    AssistantToolCallMessage(
                        content="The tool raised an internal error. Do not immediately retry the tool call and explain to the user what happened. If the user asks you to retry, you are allowed to do that.",
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                        visible=False,
                    )
                    for tool_call in tool_calls
                ]
            )

        # If this is a navigation tool call, pause the graph execution
        # so that the frontend can re-initialise Max with a new set of contextual tools.
        if navigate_tool_call:
            result = tool_results[0]
            if result.status == ToolExecutionStatus.COMPLETED:
                navigate_message = AssistantToolCallMessage(
                    content=str(result.content) if result.content else "",
                    ui_payload=result.metadata,
                    id=str(uuid4()),
                    tool_call_id=navigate_tool_call.id,
                    visible=True,
                )
                # Raising a `NodeInterrupt` ensures the assistant graph stops here and
                # surfaces the navigation confirmation to the client. The next user
                # interaction will resume the graph with potentially different
                # contextual tools.
                raise NodeInterrupt(navigate_message)

        if tool_execution_message:
            result_messages.append(tool_execution_message)

        insight_artifacts_with_query = [
            artifact
            for tool_result in tool_results
            for artifact in tool_result.artifacts
            if isinstance(artifact, InsightArtifact) and artifact.query
        ]
        # TODO: unify the visualization and multi visualization messages
        if len(insight_artifacts_with_query) > 1:
            result_messages.append(
                MultiVisualizationMessage(
                    id=str(uuid4()),
                    visualizations=[
                        VisualizationItem(
                            initiator=state.root_conversation_start_id,
                            plan=artifact.plan,
                            answer=cast(AnyAssistantGeneratedQuery, artifact.query),
                        )
                        for artifact in insight_artifacts_with_query
                    ],
                    visible=True,
                )
            )
        elif len(insight_artifacts_with_query) == 1:
            result_messages.append(
                VisualizationMessage(
                    id=str(uuid4()),
                    initiator=state.root_conversation_start_id,
                    plan=insight_artifacts_with_query[0].plan,
                    answer=cast(AnyAssistantGeneratedQuery, insight_artifacts_with_query[0].query),
                    visible=True,
                )
            )

        for result in tool_results:
            # NOTE: this accounts for the failed tool results too, content and result.metadata contain information about the failure
            result_messages.append(
                AssistantToolCallMessage(
                    content=str(result.content) if result.content else "",
                    ui_payload={result.tool_name: result.metadata},
                    id=str(uuid4()),
                    tool_call_id=result.id,
                    visible=result.send_result_to_frontend,
                )
            )

        return PartialAssistantState(
            messages=result_messages,
            root_tool_calls_count=tool_call_count + 1,
        )

    def router(self, state: AssistantState) -> RouteName:
        last_message = state.messages[-1]

        if isinstance(last_message, AssistantToolCallMessage):
            return "root"  # Let the root either proceed or finish, since it now can see the tool call result
        return "end"
