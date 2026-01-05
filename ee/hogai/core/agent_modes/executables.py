import asyncio
from collections.abc import Mapping, Sequence
from typing import Literal, TypeVar, cast
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
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeInterrupt
from langgraph.types import Send
from posthoganalytics import capture_exception
from pydantic import ValidationError

from posthog.schema import (
    AgentMode,
    AssistantMessage,
    AssistantTool,
    AssistantToolCallMessage,
    ContextMessage,
    FailureMessage,
    HumanMessage,
)

from posthog.event_usage import groups
from posthog.models import Team, User

from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder
from ee.hogai.core.agent_modes.prompts import (
    ROOT_CONVERSATION_SUMMARY_PROMPT,
    ROOT_HARD_LIMIT_REACHED_PROMPT,
    ROOT_TOOL_DOES_NOT_EXIST,
)
from ee.hogai.core.agent_modes.toolkit import AgentToolkitManager
from ee.hogai.core.executable import BaseAgentExecutable
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tool_errors import MaxToolError
from ee.hogai.utils.anthropic import add_cache_control, convert_to_anthropic_messages
from ee.hogai.utils.conversation_summarizer import AnthropicConversationSummarizer
from ee.hogai.utils.helpers import convert_tool_messages_to_dict, normalize_ai_message
from ee.hogai.utils.types import (
    AssistantMessageUnion,
    AssistantNodeName,
    AssistantState,
    PartialAssistantState,
    ReplaceMessages,
)
from ee.hogai.utils.types.base import NodePath

from .compaction_manager import AnthropicConversationCompactionManager

RootMessageUnion = HumanMessage | AssistantMessage | FailureMessage | AssistantToolCallMessage | ContextMessage
T = TypeVar("T", RootMessageUnion, BaseMessage)

logger = structlog.get_logger(__name__)


class BaseAgentLoopExecutable(BaseAgentExecutable[AssistantState, PartialAssistantState]):
    def __init__(
        self,
        *,
        team: Team,
        user: User,
        toolkit_manager_class: type[AgentToolkitManager],
        node_path: tuple[NodePath, ...],
    ):
        super().__init__(team, user, node_path)
        self._toolkit_manager_class = toolkit_manager_class


class BaseAgentLoopRootExecutable(BaseAgentLoopExecutable):
    def __init__(
        self,
        *,
        team: Team,
        user: User,
        toolkit_manager_class: type[AgentToolkitManager],
        prompt_builder_class: type[AgentPromptBuilder],
        node_path: tuple[NodePath, ...],
    ):
        super().__init__(team=team, user=user, toolkit_manager_class=toolkit_manager_class, node_path=node_path)
        self._prompt_builder_class = prompt_builder_class


class AgentExecutable(BaseAgentLoopRootExecutable):
    MAX_TOOL_CALLS = 24
    """
    Determines the maximum number of tool calls allowed in a single generation.
    """
    THINKING_CONFIG = {"type": "enabled", "budget_tokens": 1024}
    """
    Determines the thinking configuration for the model.
    """

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        toolkit_manager_class: type[AgentToolkitManager],
        prompt_builder_class: type[AgentPromptBuilder],
        node_path: tuple[NodePath, ...],
    ):
        super().__init__(
            team=team,
            user=user,
            toolkit_manager_class=toolkit_manager_class,
            prompt_builder_class=prompt_builder_class,
            node_path=node_path,
        )
        self._window_manager = AnthropicConversationCompactionManager()

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit_manager = self._toolkit_manager_class(
            team=self._team, user=self._user, context_manager=self.context_manager
        )
        prompt_builder = self._prompt_builder_class(
            team=self._team, user=self._user, context_manager=self.context_manager
        )
        tools, system_prompts = await asyncio.gather(
            *[toolkit_manager.get_tools(state, config), prompt_builder.get_prompts(state, config)]
        )

        tools = cast("list[MaxTool]", tools)
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
        current_token_count = await self._window_manager.calculate_token_count(
            model, langchain_messages, tools=tools, thinking_config=self.THINKING_CONFIG
        )
        if current_token_count > self._window_manager.CONVERSATION_WINDOW_SIZE:
            # Exclude the last message if it's the first turn.
            messages_to_summarize = langchain_messages[:-1] if self._is_first_turn(state) else langchain_messages
            summary = await AnthropicConversationSummarizer(
                self._team,
                self._user,
                extend_context_window=current_token_count > 195_000,
            ).summarize(messages_to_summarize)

            summary_message = ContextMessage(
                content=ROOT_CONVERSATION_SUMMARY_PROMPT.format(summary=summary),
                id=str(uuid4()),
            )

            # Insert the summary message before the last human message
            insertion_result = self._window_manager.update_window(
                messages_to_replace or state.messages,
                summary_message,
                state.agent_mode_or_default,
                start_id=start_id,
            )
            window_id = insertion_result.updated_window_start_id
            start_id = insertion_result.updated_start_id
            messages_to_replace = insertion_result.messages

            # Update the window
            langchain_messages = self._construct_messages(messages_to_replace, window_id, state.root_tool_calls_count)

        system_prompts = cast(list[BaseMessage], system_prompts)
        assert len(system_prompts) > 0
        # Mark the longest default prefix as cacheable
        add_cache_control(system_prompts[0], ttl="1h")

        message = await model.ainvoke(system_prompts + langchain_messages, config)

        generated_messages = self._process_output_message(message)

        # Set new tool call count
        tool_call_count = (state.root_tool_calls_count or 0) + 1 if generated_messages[-1].tool_calls else None

        # Replace the messages with the new message window
        new_messages: list[AssistantMessageUnion] | ReplaceMessages[AssistantMessageUnion]
        if messages_to_replace:
            new_messages = ReplaceMessages([*messages_to_replace, *generated_messages])
        else:
            new_messages = cast(list[AssistantMessageUnion], generated_messages)

        return PartialAssistantState(
            messages=new_messages,
            root_tool_calls_count=tool_call_count,
            root_conversation_start_id=window_id,
            start_id=start_id,
            agent_mode=self._get_updated_agent_mode(generated_messages[-1], state.agent_mode_or_default),
        )

    def router(self, state: AssistantState):
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage) or not last_message.tool_calls:
            return AssistantNodeName.END
        return [
            Send(AssistantNodeName.ROOT_TOOLS, state.model_copy(update={"root_tool_call_id": tool_call.id}))
            for tool_call in last_message.tool_calls
        ]

    def _get_model(self, state: AssistantState, tools: list["MaxTool"]):
        base_model = MaxChatAnthropic(
            model="claude-sonnet-4-5",
            streaming=True,
            stream_usage=True,
            user=self._user,
            team=self._team,
            betas=["interleaved-thinking-2025-05-14", "context-1m-2025-08-07"],
            max_tokens=8192,
            thinking=self.THINKING_CONFIG,
            conversation_start_dt=state.start_dt,
            billable=True,
        )

        # The agent can operate in loops. Since insight building is an expensive operation, we want to limit a recursion depth.
        # This will remove the functions, so the agent doesn't have any other option but to exit.
        if self._is_hard_limit_reached(state.root_tool_calls_count):
            return base_model

        return base_model.bind_tools(tools, parallel_tool_calls=True)

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

    def _process_output_message(self, message: LangchainAIMessage) -> list[AssistantMessage]:
        """Process the output message."""
        return normalize_ai_message(message)

    def _get_updated_agent_mode(self, generated_message: AssistantMessage, current_mode: AgentMode) -> AgentMode | None:
        for tool_call in generated_message.tool_calls or []:
            if tool_call.name == AssistantTool.SWITCH_MODE and (new_mode := tool_call.args.get("new_mode")):
                return new_mode
        return current_mode


class AgentToolsExecutable(BaseAgentLoopExecutable):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
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

        # Find the tool class in a toolkit.
        toolkit_manager = self._toolkit_manager_class(
            team=self._team, user=self._user, context_manager=self.context_manager
        )
        available_tools = await toolkit_manager.get_tools(state, config)
        # Filter to only MaxTool instances (dicts are server-side tools like web_search handled by Anthropic)
        tool = next(
            (tool for tool in available_tools if isinstance(tool, MaxTool) and tool.get_name() == tool_call.name), None
        )

        # If the tool doesn't exist, return the message to the agent
        if not tool:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=ROOT_TOOL_DOES_NOT_EXIST,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                ],
            )

        # Tricky: set the node path associated with the tool call
        tool.set_node_path(
            (
                *self.node_path[:-1],
                NodePath(name=AssistantNodeName.ROOT_TOOLS, message_id=last_message.id, tool_call_id=tool_call.id),
            )
        )

        try:
            result = await tool.ainvoke(
                ToolCall(type="tool_call", name=tool_call.name, args=tool_call.args, id=tool_call.id), config=config
            )
            if not isinstance(result, LangchainToolMessage):
                raise ValueError(
                    f"Tool '{tool_call.name}' returned {type(result).__name__}, expected LangchainToolMessage"
                )
        except MaxToolError as e:
            logger.exception(
                "maxtool_error", extra={"tool": tool_call.name, "error": str(e), "retry_strategy": e.retry_strategy}
            )
            user_distinct_id = self._get_user_distinct_id(config)
            capture_exception(
                e,
                distinct_id=user_distinct_id,
                properties={
                    **self._get_debug_props(config),
                    "tool": tool_call.name,
                    "retry_strategy": e.retry_strategy,
                },
            )

            if user_distinct_id:
                posthoganalytics.capture(
                    distinct_id=user_distinct_id,
                    event="max_tool_error",
                    properties={
                        **self._get_debug_props(config),
                        "tool_name": tool_call.name,
                        "error_type": e.__class__.__name__,
                        "retry_strategy": e.retry_strategy,
                        "error_message": str(e),
                    },
                    groups=groups(None, self._team),
                )

            content = f"Tool failed: {e.to_summary()}.{e.retry_hint}"
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=content,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                ],
            )
        except ValidationError as e:
            logger.exception("Validation error calling tool", extra={"tool_name": tool_call.name, "error": str(e)})
            capture_exception(
                e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
            )
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="There was a validation error calling the tool: " + str(e),
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                ],
            )
        except NodeInterrupt:
            # Let NodeInterrupt propagate to the graph engine for tool interrupts
            raise
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

        tool_message = AssistantToolCallMessage(
            content=str(result.content) if result.content else "",
            ui_payload={tool_call.name: result.artifact},
            id=str(uuid4()),
            tool_call_id=tool_call.id,
        )

        return PartialAssistantState(
            messages=[tool_message],
        )

    def router(self, state: AssistantState) -> Literal["root", "end"]:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantToolCallMessage):
            return "root"  # Let the root either proceed or finish, since it now can see the tool call result
        return "end"
