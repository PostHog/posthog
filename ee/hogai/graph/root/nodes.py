import asyncio
from collections.abc import Awaitable, Mapping, Sequence
from typing import TYPE_CHECKING, Literal, TypeVar, Union
from uuid import uuid4

import structlog
import posthoganalytics
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    ToolCall,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeInterrupt
from langgraph.types import Send
from posthoganalytics import capture_exception
from pydantic import BaseModel

from posthog.schema import AssistantMessage, AssistantToolCallMessage, ContextMessage, FailureMessage, HumanMessage

from posthog.models import Team, User

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.conversation_summarizer.nodes import AnthropicConversationSummarizer
from ee.hogai.graph.root.compaction_manager import AnthropicConversationCompactionManager
from ee.hogai.graph.shared_prompts import CORE_MEMORY_PROMPT
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.tool import ToolMessagesArtifact
from ee.hogai.utils.anthropic import add_cache_control, convert_to_anthropic_messages
from ee.hogai.utils.helpers import convert_tool_messages_to_dict, normalize_ai_message
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import (
    AssistantMessageUnion,
    AssistantNodeName,
    AssistantState,
    NodePath,
    PartialAssistantState,
    ReplaceMessages,
)
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
from .tools import (
    CreateAndQueryInsightTool,
    CreateDashboardTool,
    CreateSupportTicketTool,
    ReadDataTool,
    ReadTaxonomyTool,
    SearchTool,
    SessionSummarizationTool,
    TodoWriteTool,
)

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool

SLASH_COMMAND_INIT = "/init"
SLASH_COMMAND_REMEMBER = "/remember"


RootMessageUnion = HumanMessage | AssistantMessage | FailureMessage | AssistantToolCallMessage | ContextMessage
T = TypeVar("T", RootMessageUnion, BaseMessage)

RootTool = Union[type[BaseModel], "MaxTool"]

logger = structlog.get_logger(__name__)


class RootNode(AssistantNode):
    MAX_TOOL_CALLS = 24
    """
    Determines the maximum number of tool calls allowed in a single generation.
    """
    THINKING_CONFIG = {"type": "enabled", "budget_tokens": 1024}
    """
    Determines the thinking configuration for the model.
    """

    def __init__(self, team: Team, user: User, node_path: tuple[NodePath, ...] | None = None):
        super().__init__(team, user, node_path)
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
        start_id = state.start_id

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
            insertion_result = self._window_manager.update_window(
                messages_to_replace or state.messages, summary_message, start_id=start_id
            )
            window_id = insertion_result.updated_window_start_id
            start_id = insertion_result.updated_start_id
            messages_to_replace = insertion_result.messages

            # Update the window
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
        assistant_message = normalize_ai_message(message)

        new_messages: list[AssistantMessageUnion] = [assistant_message]
        # Replace the messages with the new message window
        if messages_to_replace:
            new_messages = ReplaceMessages([*messages_to_replace, assistant_message])

        # Set new tool call count
        tool_call_count = (state.root_tool_calls_count or 0) + 1 if assistant_message.tool_calls else None

        return PartialAssistantState(
            messages=new_messages,
            root_tool_calls_count=tool_call_count,
            root_conversation_start_id=window_id,
            start_id=start_id,
        )

    def router(self, state: AssistantState):
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage) or not last_message.tool_calls:
            return AssistantNodeName.END
        return [
            Send(AssistantNodeName.ROOT_TOOLS, state.model_copy(update={"root_tool_call_id": tool_call.id}))
            for tool_call in last_message.tool_calls
        ]

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

    def _has_support_escalation_feature_flag(self) -> bool:
        """
        Check if the user has the support escalation feature flag enabled.
        """
        return posthoganalytics.feature_enabled(
            "escalate-ai-to-support-ticket",
            str(self._user.distinct_id),
            groups={"organization": str(self._team.organization_id)},
            group_properties={"organization": {"id": str(self._team.organization_id)}},
            send_feature_flag_events=True,
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

        return base_model.bind_tools(tools, parallel_tool_calls=True)

    async def _get_tools(self, state: AssistantState, config: RunnableConfig) -> list[RootTool]:
        from ee.hogai.tool import get_contextual_tool_class

        # Static toolkit
        default_tools: list[type[MaxTool]] = [
            ReadTaxonomyTool,
            ReadDataTool,
            SearchTool,
            TodoWriteTool,
        ]

        # The contextual insights tool overrides the static tool. Only inject if it's injected.
        if not CreateAndQueryInsightTool.is_editing_mode(self.context_manager):
            default_tools.append(CreateAndQueryInsightTool)

        # Add session summarization tool if enabled
        if self._has_session_summarization_feature_flag():
            default_tools.append(SessionSummarizationTool)

        if self._has_support_escalation_feature_flag():
            default_tools.append(CreateSupportTicketTool)

        # Add other lower-priority tools
        default_tools.extend(
            [
                CreateDashboardTool,
            ]
        )

        # Processed tools
        available_tools: list[RootTool] = []

        # Initialize the static toolkit
        # We set tool_call_id to an empty string here because we don't know the tool call id yet
        # This is just to bound the tools to the model
        dynamic_tools = (
            tool_class.create_tool_class(
                team=self._team, user=self._user, state=state, config=config, context_manager=self.context_manager
            )
            for tool_class in default_tools
        )
        available_tools.extend(await asyncio.gather(*dynamic_tools))

        # Inject contextual tools
        tool_names = self.context_manager.get_contextual_tools().keys()
        awaited_contextual_tools: list[Awaitable[RootTool]] = []
        for tool_name in tool_names:
            ContextualMaxToolClass = get_contextual_tool_class(tool_name)
            if ContextualMaxToolClass is None:
                continue  # Ignoring a tool that the backend doesn't know about - might be a deployment mismatch
            awaited_contextual_tools.append(
                ContextualMaxToolClass.create_tool_class(
                    team=self._team,
                    user=self._user,
                    state=state,
                    config=config,
                    context_manager=self.context_manager,
                )
            )

        available_tools.extend(await asyncio.gather(*awaited_contextual_tools))

        return available_tools

    def _construct_messages(
        self,
        messages: Sequence[AssistantMessageUnion],
        window_start_id: str | None = None,
        tool_calls_count: int | None = None,
    ) -> list[BaseMessage]:
        conversation_window = self._window_manager.get_messages_in_window(messages, window_start_id)

        # `assistant` messages must be contiguous with the respective `tool` messages.
        tool_result_messages = self._get_tool_map(conversation_window)

        # Convert to Anthropic messages
        history = self._convert_to_langchain_messages(conversation_window, tool_result_messages)

        # Force the agent to stop if the tool call limit is reached.
        history = self._add_limit_message_if_reached(history, tool_calls_count)

        # Append a single cache control to the last human message or last tool message,
        # so we cache the full prefix of the conversation.
        history = self._add_cache_control_to_last_message(history)

        return history

    def _filter_assistant_messages(self, messages: Sequence[AssistantMessageUnion]) -> Sequence[RootMessageUnion]:
        """Filter out messages that are not part of the assistant conversation."""
        return [message for message in messages if isinstance(message, RootMessageUnion)]

    def _get_messages_in_window(
        self, messages: Sequence[AssistantMessageUnion], window_start_id: str | None = None
    ) -> Sequence[AssistantMessageUnion]:
        """Filter out messages that are not part of the conversation window."""
        filtered_messages = self._filter_assistant_messages(messages)
        return self._window_manager.get_messages_in_window(filtered_messages, window_start_id)

    def _add_limit_message_if_reached(
        self, messages: list[BaseMessage], tool_calls_count: int | None
    ) -> list[BaseMessage]:
        """Append a hard limit reached message if the tool calls count is reached."""
        if self._is_hard_limit_reached(tool_calls_count):
            return [*messages, LangchainHumanMessage(content=ROOT_HARD_LIMIT_REACHED_PROMPT)]
        return messages

    def _get_tool_map(self, messages: Sequence[AssistantMessageUnion]) -> Mapping[str, AssistantToolCallMessage]:
        """Get a map of tool call IDs to tool call messages."""
        return convert_tool_messages_to_dict(messages)

    def _convert_to_langchain_messages(
        self,
        messages: Sequence[AssistantMessageUnion],
        tool_result_messages: Mapping[str, AssistantToolCallMessage],
    ) -> list[BaseMessage]:
        """Convert a conversation window to a list of Langchain messages."""
        return convert_to_anthropic_messages(messages, tool_result_messages)

    def _add_cache_control_to_last_message(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Add cache control to the last message."""
        for i in range(len(messages) - 1, -1, -1):
            maybe_content_arr = messages[i].content
            if (
                isinstance(messages[i], LangchainHumanMessage | LangchainAIMessage)
                and isinstance(maybe_content_arr, list)
                and len(maybe_content_arr) > 0
                and isinstance(maybe_content_arr[-1], dict)
            ):
                maybe_content_arr[-1]["cache_control"] = {"type": "ephemeral"}
                break
        return messages

    def _is_hard_limit_reached(self, tool_calls_count: int | None) -> bool:
        return tool_calls_count is not None and tool_calls_count >= self.MAX_TOOL_CALLS


class RootNodeTools(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT_TOOLS

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        last_message = state.messages[-1]

        reset_state = PartialAssistantState(root_tool_call_id=None)
        # Should never happen, but just in case.
        if not isinstance(last_message, AssistantMessage) or not last_message.id or not state.root_tool_call_id:
            return reset_state

        # Find the current tool call in the last message.
        tool_call = next(
            (tool_call for tool_call in last_message.tool_calls or [] if tool_call.id == state.root_tool_call_id), None
        )
        if not tool_call:
            return reset_state

        from ee.hogai.tool import get_contextual_tool_class

        ToolClass = get_contextual_tool_class(tool_call.name)

        # If the tool doesn't exist, return the message to the agent
        if not ToolClass:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=ROOT_TOOL_DOES_NOT_EXIST,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                ],
            )

        # Initialize the tool and process it
        tool_class = await ToolClass.create_tool_class(
            team=self._team,
            user=self._user,
            # Tricky: set the node path to associated with the tool call
            node_path=(
                *self.node_path[:-1],
                NodePath(name=AssistantNodeName.ROOT_TOOLS, message_id=last_message.id, tool_call_id=tool_call.id),
            ),
            state=state,
            config=config,
            context_manager=self.context_manager,
        )

        try:
            result = await tool_class.ainvoke(
                ToolCall(type="tool_call", name=tool_call.name, args=tool_call.args, id=tool_call.id), config=config
            )
            if not isinstance(result, LangchainToolMessage):
                raise ValueError(
                    f"Tool '{tool_call.name}' returned {type(result).__name__}, expected LangchainToolMessage"
                )
        except Exception as e:
            logger.exception("Error calling tool", extra={"tool_name": tool_call.name, "error": str(e)})
            capture_exception(
                e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
            )
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="The tool raised an internal error. Do not immediately retry the tool call and explain to the user what happened. If the user asks you to retry, you are allowed to do that.",
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                ],
            )

        if isinstance(result.artifact, ToolMessagesArtifact):
            return PartialAssistantState(
                messages=result.artifact.messages,
            )

        # If this is a navigation tool call, pause the graph execution
        # so that the frontend can re-initialise Max with a new set of contextual tools.
        if tool_call.name == "navigate":
            navigate_message = AssistantToolCallMessage(
                content=str(result.content) if result.content else "",
                ui_payload={tool_call.name: result.artifact},
                id=str(uuid4()),
                tool_call_id=tool_call.id,
            )
            # Raising a `NodeInterrupt` ensures the assistant graph stops here and
            # surfaces the navigation confirmation to the client. The next user
            # interaction will resume the graph with potentially different
            # contextual tools.
            raise NodeInterrupt(navigate_message)

        tool_message = AssistantToolCallMessage(
            content=str(result.content) if result.content else "",
            ui_payload={tool_call.name: result.artifact},
            id=str(uuid4()),
            tool_call_id=tool_call.id,
        )

        return PartialAssistantState(
            messages=[tool_message],
        )

    # This is only for the Inkeep node. Remove when inkeep_docs is removed.
    def router(self, state: AssistantState) -> Literal["root", "end"]:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantToolCallMessage):
            if last_message.ui_payload and "create_support_ticket" in last_message.ui_payload:
                return "end"
            return "root"  # Let the root either proceed or finish, since it now can see the tool call result
        return "end"
