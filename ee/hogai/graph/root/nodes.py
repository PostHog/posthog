import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, Optional, TypeVar, cast
from uuid import uuid4

import structlog
import posthoganalytics
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
)
from langchain_core.prompts import ChatPromptTemplate
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
    PlanningMessage,
    PlanningStep,
    ReasoningMessage,
    ToolExecutionStatus,
    VisualizationMessage,
)

from posthog.models import Team, User

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.conversation_summarizer.nodes import AnthropicConversationSummarizer
from ee.hogai.graph.root.compaction_manager import AnthropicConversationCompactionManager
from ee.hogai.graph.root.tools.todo_write import TodoWriteTool
from ee.hogai.graph.shared_prompts import CORE_MEMORY_PROMPT
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.tool import MaxTool, ParallelToolExecution
from ee.hogai.tool.base import get_assistant_tool_class
from ee.hogai.utils.anthropic import add_cache_control, convert_to_anthropic_messages, normalize_ai_anthropic_message
from ee.hogai.utils.helpers import insert_messages_before_start
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types import (
    AssistantMessageUnion,
    AssistantNodeName,
    AssistantState,
    BaseState,
    PartialAssistantState,
    ReplaceMessages,
)
from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery, InsightArtifact, ToolResult
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    ROOT_BILLING_CONTEXT_ERROR_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT,
    ROOT_CONVERSATION_SUMMARY_PROMPT,
    ROOT_GROUPS_PROMPT,
    ROOT_HARD_LIMIT_REACHED_PROMPT,
    ROOT_SYSTEM_PROMPT,
    ROOT_TOOL_DOES_NOT_EXIST,
)

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool

logger = structlog.get_logger(__name__)

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
    MAX_TOOL_CALLS = 24
    """
    Determines the maximum number of tool calls allowed in a single generation.
    """
    THINKING_CONFIG = {"type": "enabled", "budget_tokens": 1024}
    """
    Determines the thinking configuration for the model.
    """

    def __init__(self, team: Team, user: User):
        super().__init__(team, user)
        self._window_manager = AnthropicConversationCompactionManager()

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        # Add context messages on start of the conversation.
        tools, billing_context_prompt, core_memory, groups = await asyncio.gather(
            self._get_tools(state, config),
            self._get_billing_prompt(config),
            self._aget_core_memory_text(),
            self.context_manager.get_group_names(),
        )
        model = self._get_model(state, tools)

        # Add context messages on start of the conversation.
        messages_to_replace: Sequence[AssistantMessageUnion] = []
        if self._is_first_turn(state) and (
            updated_messages := await self.context_manager.get_state_messages_with_context(state)
        ):
            messages_to_replace = updated_messages

        # Calculate the initial window.
        langchain_messages = self._construct_messages(
            messages_to_replace or state.messages, state.root_conversation_start_id, state.root_tool_calls_count
        )
        window_id = state.root_conversation_start_id

        # Summarize the conversation if it's too long.
        if await self._window_manager.should_compact_conversation(
            model, langchain_messages, tools=tools, thinking_config=self.THINKING_CONFIG
        ):
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
            window_id = self._window_manager.find_window_boundary(messages_to_replace)
            langchain_messages = self._construct_messages(messages_to_replace, window_id, state.root_tool_calls_count)

        system_prompts = ChatPromptTemplate.from_messages(
            [
                ("system", ROOT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        ).format_messages(
            groups_prompt=f" {format_prompt_string(ROOT_GROUPS_PROMPT, groups=', '.join(groups))}" if groups else "",
            billing_context=billing_context_prompt,
            core_memory_prompt=format_prompt_string(CORE_MEMORY_PROMPT, core_memory=core_memory),
        )

        # Mark the longest default prefix as cacheable
        add_cache_control(system_prompts[-1])

        message = await model.ainvoke(system_prompts + langchain_messages, config)
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

    async def _get_billing_prompt(self, config: RunnableConfig) -> str:
        """Get billing information including whether to include the billing tool and the prompt.
        Returns:
            str: prompt
        """
        has_billing_context = self.context_manager.get_billing_context() is not None
        has_access = await self.context_manager.check_user_has_billing_access()

        if has_access and not has_billing_context:
            return ROOT_BILLING_CONTEXT_ERROR_PROMPT

        prompt = (
            ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT
            if has_access and has_billing_context
            else ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT
        )
        return prompt

    def _get_model(self, state: AssistantState, tools: list[MaxTool]):
        base_model = MaxChatAnthropic(
            model_name="claude-sonnet-4-5",
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
        if self._is_hard_limit_reached(state.root_tool_calls_count):
            return base_model

        tool_functions = [tool.tool_function_description for tool in tools]
        return base_model.bind_tools(tool_functions, parallel_tool_calls=True)

    async def _get_tools(self, state: AssistantState, config: RunnableConfig) -> list[MaxTool]:
        from ee.hogai.tool import get_assistant_tool_class

        from .tools import (
            CreateDashboardTool,
            CreateInsightTool,
            ReadDataTool,
            ReadTaxonomyTool,
            SearchTool,
            SessionSummarizationTool,
        )

        # Always available tools
        tool_classes = [
            ReadTaxonomyTool,
            ReadDataTool,
            SearchTool,
            TodoWriteTool,
            CreateDashboardTool,
        ]

        # # Check if session summarization is enabled for the user
        if self._has_session_summarization_feature_flag():
            tool_classes.append(SessionSummarizationTool)

        tool_names = self.context_manager.get_contextual_tools().keys()
        for tool_name in tool_names:
            ToolClass = get_assistant_tool_class(tool_name)
            if ToolClass is None:
                continue  # Ignoring a tool that the backend doesn't know about - might be a deployment mismatch
            tool_classes.append(ToolClass)

        is_editing_insight = AssistantTool.CREATE_AND_QUERY_INSIGHT in tool_names
        if not is_editing_insight:
            tool_classes.append(CreateInsightTool)

        available_tools = await asyncio.gather(
            *[
                tool.create_tool_class(
                    team=self._team, user=self._user, state=state, config=config, context_manager=self.context_manager
                )
                for tool in tool_classes
            ]
        )

        return available_tools

    def _construct_messages(
        self,
        messages: Sequence[AssistantMessageUnion],
        window_start_id: str | None = None,
        tool_calls_count: int | None = None,
    ) -> list[BaseMessage]:
        # Filter out messages that are not part of the conversation window.
        filtered_messages = [message for message in messages if isinstance(message, RootMessageUnion)]
        conversation_window = self._window_manager.get_messages_in_window(filtered_messages, window_start_id)

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

    def _is_hard_limit_reached(self, tool_calls_count: int | None) -> bool:
        return tool_calls_count is not None and tool_calls_count >= self.MAX_TOOL_CALLS


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

        logger.info(f"Tool calls: {tool_calls}")

        single_tool_call_names = ["navigate", "todo_write"]
        single_tool_call = next(
            (tool_call for tool_call in tool_calls if tool_call.name in single_tool_call_names), None
        )
        if single_tool_call and len(tool_calls) > 1:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=f"Do not use the {single_tool_call.name} in combination with other tools.",
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                        visible=False,
                    )
                    for tool_call in tool_calls
                ],
                root_tool_calls_count=tool_call_count + 1,
            )

        result_messages: list[AssistantMessageUnion] = []

        non_existent_tool_calls = 0
        for tool_call in tool_calls:
            if get_assistant_tool_class(tool_call.name) is None:
                result_messages.append(
                    AssistantToolCallMessage(
                        content=ROOT_TOOL_DOES_NOT_EXIST,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                )
                non_existent_tool_calls += 1

        if non_existent_tool_calls == len(tool_calls):
            return PartialAssistantState(
                messages=result_messages,
                root_tool_calls_count=tool_call_count + 1,
            )

        ToolExecutionClass = ParallelToolExecution(
            team=self._team, user=self._user, write_message_afunc=self._write_message
        )
        tool_results: list[ToolResult] = []
        tool_execution_message = None
        try:
            tool_results, tool_execution_message = await ToolExecutionClass.arun(tool_calls, state, config)
        except Exception as e:
            logger.exception("Error executing tools", error=e)
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
        if single_tool_call and single_tool_call.name == "navigate":
            result = tool_results[0]
            if result.status == ToolExecutionStatus.COMPLETED:
                navigate_message = AssistantToolCallMessage(
                    content=str(result.content) if result.content else "",
                    ui_payload=result.metadata,
                    id=str(uuid4()),
                    tool_call_id=single_tool_call.id,
                    visible=True,
                )
                # Raising a `NodeInterrupt` ensures the assistant graph stops here and
                # surfaces the navigation confirmation to the client. The next user
                # interaction will resume the graph with potentially different
                # contextual tools.
                raise NodeInterrupt(navigate_message)

        if tool_execution_message:
            result_messages.append(tool_execution_message)

        if single_tool_call and single_tool_call.name == "todo_write":
            result_messages.append(
                PlanningMessage(
                    id=str(uuid4()),
                    steps=[
                        PlanningStep(
                            description=todo["description"],
                            status=todo["status"],
                        )
                        for todo in single_tool_call.args["todos"]
                    ],
                )
            )

        insight_artifacts_with_query = [
            artifact
            for tool_result in tool_results
            for artifact in tool_result.artifacts
            if isinstance(artifact, InsightArtifact) and artifact.query
        ]
        if len(insight_artifacts_with_query) > 0:
            result_messages.extend(
                [
                    VisualizationMessage(
                        id=str(uuid4()),
                        initiator=state.root_conversation_start_id,
                        plan=artifact.plan,
                        answer=cast(AnyAssistantGeneratedQuery, artifact.query),
                        visible=True,
                    )
                    for artifact in insight_artifacts_with_query
                ]
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
