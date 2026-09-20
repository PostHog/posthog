"""Keep the report agent's prompt inside the model's input budget.

``create_react_agent`` appends every tool result to the message history and never drops
one, so the prompt grows with each step of a run. The detail tools return whole traces,
sessions and generation payloads, so a few of them are enough to push a later call past
what the provider accepts. The provider then rejects that call with a 400, the agent
raises, and the run falls back to a stub report that throws away the analysis already
done.

``trim_agent_messages`` runs as the agent's ``pre_model_hook``. It caps a single oversized
tool result, then drops the oldest messages until the prompt fits the budget. It rewrites
only what is sent to the model — the graph state keeps the full history, so the report the
agent has built up is unaffected.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

# The ceiling for the message history of one model call. The system prompt and the tool
# schemas sit on top of it, so the real prompt runs a few thousand tokens higher. Runs that
# failed sent a little over 160k tokens of history, so this stays clear of the point the
# provider rejected while leaving the agent room to read several traces before anything goes.
MAX_PROMPT_TOKENS = 120_000
# The ceiling for one tool result. Every bounded tool fits well inside this, so only the
# tools that return raw event payloads are ever cut.
MAX_TOOL_RESULT_TOKENS = 30_000
# count_tokens_approximately defaults to 4 characters per token, which undercounts the
# UUID-dense JSON these tools return. Counting against a denser ratio keeps the estimate
# on the safe side of the real tokenizer.
CHARS_PER_TOKEN = 3.0
# Never trim below the tool result the agent is waiting on and the call that asked for it.
MIN_KEPT_MESSAGES = 2

TOOL_RESULT_TRUNCATED_NOTE = (
    "\n\n[Truncated: this result was too large to keep in context. Narrow the request: ask for "
    "fewer items, or inspect one ID at a time. Do not repeat this call unchanged.]"
)


def _token_count(messages: Sequence[BaseMessage]) -> int:
    return count_tokens_approximately(messages, chars_per_token=CHARS_PER_TOKEN)


def _cap_tool_result(message: ToolMessage) -> ToolMessage:
    """Return the tool result capped to MAX_TOOL_RESULT_TOKENS, keeping its head."""
    if not isinstance(message.content, str):
        return message
    max_chars = int(MAX_TOOL_RESULT_TOKENS * CHARS_PER_TOKEN)
    if len(message.content) <= max_chars:
        return message
    capped = message.model_copy()
    capped.content = message.content[:max_chars] + TOOL_RESULT_TRUNCATED_NOTE
    return capped


def trim_agent_messages(state: dict[str, Any]) -> dict[str, list[AnyMessage]]:
    """Return the message history to send to the model, capped and trimmed to budget."""
    messages: list[AnyMessage] = [
        _cap_tool_result(message) if isinstance(message, ToolMessage) else message for message in state["messages"]
    ]
    # Pin the opening request so the agent keeps its task even after a deep trim.
    pinned = messages[:1] if messages and isinstance(messages[0], HumanMessage) else []
    tail = messages[len(pinned) :]
    counts = [_token_count([message]) for message in tail]
    total = _token_count(pinned) + sum(counts)

    dropped = 0
    while len(tail) - dropped > MIN_KEPT_MESSAGES and total > MAX_PROMPT_TOKENS:
        total -= counts[dropped]
        dropped += 1

    # A tool result whose request was dropped answers nothing, and providers reject it,
    # so drop the orphans the trim exposed.
    while dropped < len(tail) and isinstance(tail[dropped], ToolMessage):
        dropped += 1

    return {"llm_input_messages": [*pinned, *tail[dropped:]]}
