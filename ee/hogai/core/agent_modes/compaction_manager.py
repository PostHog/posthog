import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any, TypeVar, cast
from uuid import uuid4

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
)
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ValidationError

from posthog.schema import (
    AgentMode,
    AssistantMessage,
    AssistantTool,
    AssistantToolCallMessage,
    ContextMessage,
    HumanMessage,
)

from posthog.sync import database_sync_to_async

from ee.hogai.context.prompts import CONTEXT_INITIAL_MODE_PROMPT
from ee.hogai.core.agent_modes.prompts import ROOT_AGENT_MODE_REMINDER_PROMPT, ROOT_TODO_REMINDER_PROMPT
from ee.hogai.tools.todo_write import TodoWriteTool
from ee.hogai.utils.helpers import find_start_message, find_start_message_idx, insert_messages_before_start
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types import AssistantMessageUnion

T = TypeVar("T", bound=AssistantMessageUnion)

LangchainTools = Sequence[dict[str, Any] | type | Callable | BaseTool]


class InsertionResult(BaseModel):
    messages: Sequence[AssistantMessageUnion]
    updated_start_id: str
    updated_window_start_id: str


class ConversationCompactionManager(ABC):
    """
    Manages conversation window boundaries, message filtering, and summarization decisions.
    """

    CONVERSATION_WINDOW_SIZE = 100_000
    """
    Determines the maximum number of tokens allowed in the conversation window.
    """
    APPROXIMATE_TOKEN_LENGTH = 4
    """
    Determines the approximate number of characters per token.
    """

    def find_window_boundary(self, messages: Sequence[T], max_messages: int = 10, max_tokens: int = 1000) -> str | None:
        """
        Find the optimal window start ID based on message count and token limits.
        Ensures the window starts at a human or assistant message.
        """

        new_window_id: str | None = None
        for message in reversed(messages):
            # Handle limits before assigning the window ID.
            max_tokens -= self._get_estimated_assistant_message_tokens(message)
            max_messages -= 1
            if max_tokens < 0 or max_messages < 0:
                break

            # Assign the new new window ID.
            if message.id is not None:
                if isinstance(message, HumanMessage):
                    new_window_id = message.id
                if isinstance(message, AssistantMessage):
                    new_window_id = message.id

        return new_window_id

    def get_messages_in_window(self, messages: Sequence[T], window_start_id: str | None = None) -> Sequence[T]:
        """
        Filter messages to only those within the conversation window.
        """
        if window_start_id is not None:
            return self._get_conversation_window(messages, window_start_id)
        return messages

    async def should_compact_conversation(
        self, model: BaseChatModel, messages: list[BaseMessage], tools: LangchainTools | None = None, **kwargs
    ) -> bool:
        """
        Determine if the conversation should be summarized based on token count.
        Avoids summarizing if there are only two human messages or fewer.
        """
        return await self.calculate_token_count(model, messages, tools, **kwargs) > self.CONVERSATION_WINDOW_SIZE

    async def calculate_token_count(
        self, model: BaseChatModel, messages: list[BaseMessage], tools: LangchainTools | None = None, **kwargs
    ) -> int:
        """
        Calculate the token count for a conversation.
        """
        # Avoid summarizing the conversation if there is only two human messages.
        human_messages = [message for message in messages if isinstance(message, LangchainHumanMessage)]
        if tools:
            # Filter out server-side tools for token counting purposes
            tools = [
                tool
                for tool in tools
                if not (isinstance(tool, dict) and tool.get("type", "").startswith("web_search_"))
            ]
        if len(human_messages) <= 2:
            tool_tokens = self._get_estimated_tools_tokens(tools) if tools else 0
            return sum(self._get_estimated_langchain_message_tokens(message) for message in messages) + tool_tokens
        return await self._get_token_count(model, messages, tools, **kwargs)

    def update_window(
        self,
        messages: Sequence[T],
        summary_message: ContextMessage,
        agent_mode: AgentMode,
        start_id: str | None = None,
    ) -> InsertionResult:
        """Finds the optimal position to insert the summary message in the conversation window."""
        window_start_id_candidate = self.find_window_boundary(messages, max_messages=16, max_tokens=2048)
        start_message = find_start_message(messages, start_id)
        if not start_message:
            raise ValueError("Start message not found")

        start_message_copy = start_message.model_copy(deep=True)
        start_message_copy.id = str(uuid4())

        # The last messages were too large to fit into the window. Copy the last human message to the start of the window.
        if not window_start_id_candidate:
            return self._handle_no_window_boundary(messages, summary_message, start_message_copy, agent_mode)

        # Find the updated window
        start_message_idx = find_start_message_idx(messages, window_start_id_candidate)
        new_window = messages[start_message_idx:]

        # If the start human message is in the window, insert the summary message before it
        # and update the window start.
        if start_id and next((m for m in new_window if m.id == start_id), None):
            return self._handle_start_in_window(
                messages,
                summary_message,
                start_id,
                window_start_id_candidate,
                agent_mode,
            )

        # If the start message is not in the window, insert the summary message and human message at the start of the window.
        return self._handle_start_outside_window(
            new_window,
            summary_message,
            start_message_copy,
            window_start_id_candidate,
            agent_mode,
            all_messages=messages,
        )

    def _handle_no_window_boundary(
        self,
        messages: Sequence[T],
        summary_message: ContextMessage,
        start_message_copy: HumanMessage,
        agent_mode: AgentMode,
    ) -> InsertionResult:
        """Handle case where no window boundary was found (messages too large)."""
        # Build the new window
        new_window_messages: Sequence[AssistantMessageUnion] = [summary_message, start_message_copy]

        # Prepare result messages with summary and start
        result_messages = [*messages, summary_message, start_message_copy]

        # Insert todo and/or mode reminders between summary and start
        summary_id = summary_message.id
        if summary_id:
            result_messages_with_reminders = self._insert_reminders_after_summary(
                result_messages, summary_id, agent_mode, all_messages=messages, window_messages=new_window_messages
            )
        else:
            result_messages_with_reminders = result_messages

        return InsertionResult(
            messages=result_messages_with_reminders,
            updated_start_id=start_message_copy.id,
            updated_window_start_id=summary_message.id,
        )

    def _handle_start_in_window(
        self,
        messages: Sequence[T],
        summary_message: ContextMessage,
        start_id: str,
        window_start_id_candidate: str,
        agent_mode: AgentMode,
    ) -> InsertionResult:
        """Handle case where start message is within the window boundary."""
        # Insert summary before start message
        updated_messages = insert_messages_before_start(messages, [summary_message], start_id=start_id)

        # Calculate the actual window from window_start_id_candidate onwards
        start_message_idx = find_start_message_idx(messages, window_start_id_candidate)
        window_messages = messages[start_message_idx:]

        # Insert todo and/or mode reminders after summary
        if summary_message.id:
            updated_messages = list(
                self._insert_reminders_after_summary(
                    updated_messages,
                    summary_message.id,
                    agent_mode,
                    all_messages=messages,
                    window_messages=window_messages,
                )
            )

        return InsertionResult(
            messages=updated_messages,
            updated_start_id=start_id,
            updated_window_start_id=window_start_id_candidate,
        )

    def _handle_start_outside_window(
        self,
        new_window: Sequence[T],
        summary_message: ContextMessage,
        start_message_copy: HumanMessage,
        window_start_id_candidate: str,
        agent_mode: AgentMode,
        all_messages: Sequence[T] | None = None,
    ) -> InsertionResult:
        """Handle case where start message is outside the window boundary."""
        # Insert summary and start copy at the beginning of window
        updated_messages = list(
            insert_messages_before_start(
                new_window, [summary_message, start_message_copy], start_id=window_start_id_candidate
            )
        )

        # Insert todo and/or mode reminders after summary
        # The window is the new_window (which will be checked for mode/todo presence)
        summary_id = summary_message.id
        if summary_id:
            updated_messages = list(
                self._insert_reminders_after_summary(
                    updated_messages, summary_id, agent_mode, all_messages=all_messages, window_messages=new_window
                )
            )

        return InsertionResult(
            messages=updated_messages,
            updated_start_id=start_message_copy.id,
            updated_window_start_id=window_start_id_candidate,
        )

    def _insert_reminders_after_summary(
        self,
        messages: Sequence[T],
        summary_id: str,
        agent_mode: AgentMode,
        all_messages: Sequence[T] | None = None,
        window_messages: Sequence[T] | None = None,
    ) -> Sequence[T]:
        """
        Insert both todo reminder (if needed) and mode reminder (if needed) after summary.
        Order: summary → todo reminder → mode reminder → rest

        Args:
            messages: The messages list to insert into
            summary_id: ID of the summary message
            agent_mode: Current agent mode for mode reminder
            all_messages: Full message history for finding todo (defaults to messages if None)
            window_messages: Messages in the new window for checking presence (defaults to messages if None)

        Returns:
            Updated messages with reminders inserted
        """
        if all_messages is None:
            all_messages = messages
        if window_messages is None:
            window_messages = messages

        # Determine what needs to be inserted
        reminders_to_insert: list[T] = []

        # 1. Todo reminder (if needed)
        if todo_reminder := self._get_todo_reminder_message(all_messages, window_messages):
            reminders_to_insert.append(cast(T, todo_reminder))

        # 2. Mode reminder (if needed)
        if mode_reminder := self._get_mode_message_with_context(window_messages, all_messages, agent_mode):
            reminders_to_insert.append(cast(T, mode_reminder))

        # If nothing to insert, return original messages
        if not reminders_to_insert:
            return messages

        # Insert all reminders right after summary
        summary_idx = next(i for i, msg in enumerate(messages) if msg.id == summary_id)
        result: Sequence[T] = [
            *messages[: summary_idx + 1],
            *reminders_to_insert,
            *messages[summary_idx + 1 :],
        ]
        return result

    def _get_estimated_assistant_message_tokens(self, message: AssistantMessageUnion) -> int:
        """
        Estimate token count for a message using character/4 heuristic.
        """
        char_count = 0
        if isinstance(message, HumanMessage):
            char_count = len(message.content)
        elif isinstance(message, AssistantMessage):
            char_count = len(message.content) + sum(
                len(json.dumps(m.args, separators=(",", ":"))) for m in message.tool_calls or []
            )
        elif isinstance(message, AssistantToolCallMessage):
            char_count = len(message.content)
        return round(char_count / self.APPROXIMATE_TOKEN_LENGTH)

    def _get_estimated_langchain_message_tokens(self, message: BaseMessage) -> int:
        """
        Estimate token count for a message using character/4 heuristic.
        """
        char_count = 0
        if isinstance(message.content, str):
            char_count = len(message.content)
        else:
            for content in message.content:
                if isinstance(content, str):
                    char_count += len(content)
                elif isinstance(content, dict):
                    char_count += self._count_json_tokens(content)
        if isinstance(message, LangchainAIMessage) and message.tool_calls:
            for tool_call in message.tool_calls:
                char_count += len(json.dumps(tool_call, separators=(",", ":")))
        return round(char_count / self.APPROXIMATE_TOKEN_LENGTH)

    def _get_conversation_window(self, messages: Sequence[T], start_id: str) -> Sequence[T]:
        """
        Get messages from the start_id onwards.
        """
        for idx, message in enumerate(messages):
            if message.id == start_id:
                return messages[idx:]
        return messages

    def _get_estimated_tools_tokens(self, tools: LangchainTools) -> int:
        """
        Estimate token count for tools by converting them to JSON schemas.
        """
        if not tools:
            return 0

        total_chars = 0
        for tool in tools:
            tool_schema = convert_to_openai_tool(tool)
            total_chars += self._count_json_tokens(tool_schema)
        return round(total_chars / self.APPROXIMATE_TOKEN_LENGTH)

    def _count_json_tokens(self, json_data: dict) -> int:
        return len(json.dumps(json_data, separators=(",", ":")))

    @abstractmethod
    async def _get_token_count(
        self,
        model: Any,
        messages: list[BaseMessage],
        tools: LangchainTools | None = None,
        thinking_config: dict[str, Any] | None = None,
        **kwargs,
    ) -> int:
        raise NotImplementedError

    def _get_mode_message_with_context(
        self,
        window_messages: Sequence[AssistantMessageUnion],
        all_messages: Sequence[AssistantMessageUnion],
        agent_mode: AgentMode,
    ) -> ContextMessage | None:
        """
        Get mode reminder message with context-aware checking.
        Checks initial mode message in all_messages, but mode evidence in window_messages.
        """
        # Check if initial mode message exists in full history
        if self._has_initial_mode_message(all_messages):
            return None
        # Check if mode is evident in the current window
        if self._is_mode_evident_in_window(window_messages):
            return None
        return ContextMessage(
            content=ROOT_AGENT_MODE_REMINDER_PROMPT.format(mode=agent_mode.value),
            id=str(uuid4()),
        )

    def _should_add_mode_reminder(self, messages: Sequence[AssistantMessageUnion]) -> bool:
        """
        Determine if a mode reminder should be added to the messages.
        Returns True if:
        - agent_mode is set
        - mode is not evident in the messages (no switch_mode call for current mode)
        - initial mode message is not present in the messages
        """
        if self._has_initial_mode_message(messages):
            return False
        if self._is_mode_evident_in_window(messages):
            return False
        return True

    def _is_mode_evident_in_window(self, messages: Sequence[AssistantMessageUnion]) -> bool:
        """
        Check if the current agent mode is evident in the conversation window.
        Returns True if there's a switch_mode tool call for the current mode in the messages.
        """

        for message in messages:
            if isinstance(message, AssistantMessage) and message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.name == AssistantTool.SWITCH_MODE:
                        return True
        return False

    def _has_initial_mode_message(self, messages: Sequence[AssistantMessageUnion]) -> bool:
        """
        Check if the initial mode message from the context manager is present in the messages.
        """
        for message in messages:
            if isinstance(message, ContextMessage) and CONTEXT_INITIAL_MODE_PROMPT in message.content:
                return True
        return False

    def _find_last_todo_write_message(self, messages: Sequence[T]) -> AssistantMessage | None:
        """
        Find the last AssistantMessage with a TODO_WRITE tool call.
        Searches backwards through ALL messages (not just window).

        Returns:
            The last AssistantMessage containing a TODO_WRITE tool call, or None.
        """
        for message in reversed(messages):
            if isinstance(message, AssistantMessage) and message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.name == AssistantTool.TODO_WRITE:
                        return message
        return None

    def _is_todo_in_window(self, todo_message: AssistantMessage, window_messages: Sequence[T]) -> bool:
        """
        Check if the todo message is present in the given window.

        Args:
            todo_message: The AssistantMessage containing TODO_WRITE tool call
            window_messages: Messages in the current window

        Returns:
            True if todo_message is found in window_messages (by ID or object identity)
        """
        # Check by ID if available
        if todo_message.id:
            return any(msg.id == todo_message.id for msg in window_messages)

        # Fall back to object identity check if no ID
        return any(msg is todo_message for msg in window_messages)

    def _get_todo_reminder_message(self, messages: Sequence[T], window_messages: Sequence[T]) -> HumanMessage | None:
        """
        Create a todo reminder message if:
        1. A TODO_WRITE tool call exists in the conversation
        2. That todo message is NOT in the new window

        Args:
            messages: All messages (for finding the last todo)
            window_messages: Messages in the new window (for checking if todo is present)

        Returns:
            HumanMessage containing the todo reminder, or None if no reminder needed
        """
        # Find the last TODO_WRITE tool call
        todo_message = self._find_last_todo_write_message(messages)
        if not todo_message:
            return None

        # Check if it's already in the window
        if self._is_todo_in_window(todo_message, window_messages):
            return None

        # Extract the todo list from the tool call
        if not todo_message.tool_calls:
            return None

        todo_tool_call = next(
            (tc for tc in todo_message.tool_calls if tc.name == AssistantTool.TODO_WRITE),
            None,
        )
        if not todo_tool_call:
            return None

        # Format the reminder message using TodoWriteTool
        try:
            todo_content = TodoWriteTool.format_todo_list(todo_tool_call.args)
        except ValidationError:
            return None

        reminder_content = format_prompt_string(ROOT_TODO_REMINDER_PROMPT, todo_content=todo_content)
        return HumanMessage(content=reminder_content, id=str(uuid4()))


class AnthropicConversationCompactionManager(ConversationCompactionManager):
    async def _get_token_count(
        self,
        model: ChatAnthropic,
        messages: list[BaseMessage],
        tools: LangchainTools | None = None,
        thinking_config: dict[str, Any] | None = None,
        **kwargs,
    ) -> int:
        return await database_sync_to_async(model.get_num_tokens_from_messages, thread_sensitive=False)(
            messages, thinking=thinking_config, tools=tools
        )
