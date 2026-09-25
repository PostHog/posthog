import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
)

# Blocks whose text cannot be shortened: Anthropic validates a thinking signature against the
# exact text it returned, and a server-side tool block is opaque to us.
UNTRUNCATABLE_BLOCK_TYPES = frozenset(
    {"thinking", "redacted_thinking", "server_tool_use", "web_search_tool_result", "tool_use"}
)

TextWriter = Callable[[str], None]


class ConversationInputBudget:
    """Fits a conversation into a token budget by shortening its largest message bodies.

    Compaction starts once the window passes its size limit, but nothing bounds how far a single
    turn pushes the window past that limit first, and the summarizer then has to send the whole
    window in one request. One large tool result is enough to put that request over the model's
    context limit, which the model rejects outright.

    Bodies are shortened rather than messages dropped: dropping an assistant message orphans the
    tool result that follows it, which Anthropic rejects as well.
    """

    APPROXIMATE_TOKEN_LENGTH = 4
    """Approximate number of characters per token."""

    TRUNCATION_NOTICE = "\n\n[Truncated to fit the summarization request.]"

    def __init__(self, max_tokens: int):
        self._max_chars = max_tokens * self.APPROXIMATE_TOKEN_LENGTH

    def apply(self, messages: Sequence[BaseMessage]) -> list[BaseMessage]:
        """Return the conversation with its largest bodies shortened enough to fit the budget."""
        if self._count_chars(messages) <= self._max_chars:
            return list(messages)

        bounded = [message.model_copy(deep=True) for message in messages]
        slots = self._collect_slots(bounded)
        sizes = [len(text) for text, _ in slots]
        # Everything the budget has to hold that this class cannot shorten: block scaffolding,
        # thinking blocks, and tool call arguments.
        fixed_chars = self._count_chars(bounded) - sum(sizes)
        cap = self._slot_cap(sizes, max(self._max_chars - fixed_chars, 0))

        for text, write in slots:
            if len(text) > cap:
                write(self._truncate(text, cap))
        return bounded

    def _slot_cap(self, sizes: list[int], available: int) -> int:
        """Find the highest per-body character cap that keeps the total within `available`.

        Bodies under the cap are left alone, so the space goes to the many small messages first
        and only the few large ones pay for it.
        """
        remaining = available
        for index, size in enumerate(sorted(sizes)):
            slots_left = len(sizes) - index
            if size * slots_left <= remaining:
                remaining -= size
                continue
            return remaining // slots_left
        return max(sizes, default=0)

    def _truncate(self, text: str, cap: int) -> str:
        if cap <= len(self.TRUNCATION_NOTICE):
            return text[:cap]
        return text[: cap - len(self.TRUNCATION_NOTICE)] + self.TRUNCATION_NOTICE

    def _collect_slots(self, messages: Sequence[BaseMessage]) -> list[tuple[str, TextWriter]]:
        slots: list[tuple[str, TextWriter]] = []
        for message in messages:
            if isinstance(message.content, str):
                slots.append((message.content, self._attribute_writer(message)))
                continue
            for index, block in enumerate(message.content):
                if isinstance(block, str):
                    slots.append((block, self._item_writer(message.content, index)))
                elif isinstance(block, dict) and (key := self._truncatable_key(block)):
                    slots.append((block[key], self._item_writer(block, key)))
        return slots

    def _truncatable_key(self, block: dict[str, Any]) -> str | None:
        if block.get("type") in UNTRUNCATABLE_BLOCK_TYPES:
            return None
        # `text` carries a text block, `content` the body of a tool result.
        for key in ("text", "content"):
            if isinstance(block.get(key), str):
                return key
        return None

    def _attribute_writer(self, message: BaseMessage) -> TextWriter:
        def write(text: str) -> None:
            message.content = text

        return write

    def _item_writer(self, container: Any, key: Any) -> TextWriter:
        def write(text: str) -> None:
            container[key] = text

        return write

    def _count_chars(self, messages: Sequence[BaseMessage]) -> int:
        return sum(self._count_message_chars(message) for message in messages)

    def _count_message_chars(self, message: BaseMessage) -> int:
        char_count = 0
        if isinstance(message.content, str):
            char_count = len(message.content)
        else:
            for block in message.content:
                char_count += self._count_block_chars(block)
        if isinstance(message, LangchainAIMessage) and message.tool_calls:
            for tool_call in message.tool_calls:
                char_count += self._count_json_chars(tool_call)
        return char_count

    def _count_block_chars(self, block: Any) -> int:
        """Count a content block, holding the body this class can shorten separate from the rest.

        A body is counted raw while its block is counted as JSON, so that shortening a body by one
        character always takes exactly one character off the total. Counting the body as JSON too
        would let its escapes grow the total and put the result back over the budget.
        """
        if isinstance(block, str):
            return len(block)
        if not isinstance(block, dict):
            return self._count_json_chars(block)
        key = self._truncatable_key(block)
        if key is None:
            return self._count_json_chars(block)
        return len(block[key]) + self._count_json_chars({**block, key: ""})

    def _count_json_chars(self, value: Any) -> int:
        return len(json.dumps(value, separators=(",", ":"), default=str))
