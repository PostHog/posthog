"""Keep the report agent's prompt inside the model's input budget.

``create_react_agent`` appends every tool result to the message history and never drops
one, so the prompt grows with each step of a run. The detail tools return whole traces,
sessions and generation payloads, so a few of them are enough to push a later call past
what the provider accepts. The provider then rejects that call with a 400, the agent
raises, and the run falls back to a stub report that throws away the analysis already
done.

``trim_agent_messages`` runs as the agent's ``pre_model_hook``. It caps a single oversized
tool result, then drops the oldest turns until the prompt fits the budget. It rewrites
only what is sent to the model — the graph state keeps the full history, so the report the
agent has built up is unaffected.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage
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

TOOL_RESULT_TRUNCATED_NOTE = (
    "\n\n[Truncated: this result was too large to keep in context. Narrow the request: ask for "
    "fewer items, or inspect one ID at a time. Do not repeat this call unchanged.]"
)


def _token_count(messages: Sequence[BaseMessage]) -> int:
    return count_tokens_approximately(messages, chars_per_token=CHARS_PER_TOKEN)


def _truncated_to(message: ToolMessage, max_tokens: int) -> ToolMessage:
    """Return the tool result cut to `max_tokens`, keeping its head, or the message itself.

    The note counts against the cut, so the result never comes back over its budget.
    """
    if not isinstance(message.content, str):
        return message
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    if len(message.content) <= max_chars:
        return message
    truncated = message.model_copy()
    truncated.content = message.content[: max(0, max_chars - len(TOOL_RESULT_TRUNCATED_NOTE))] + (
        TOOL_RESULT_TRUNCATED_NOTE
    )
    return truncated


def _pending_turn_start(messages: Sequence[AnyMessage]) -> int:
    """Return the index where the turn the model is waiting on begins.

    Everything from the last tool-calling AIMessage onward is one request and its results.
    The model cannot answer a tool call whose result went missing, and it cannot read a
    result whose request went missing, so the trim stops here and shrinks the results
    instead of breaking the pair.
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, AIMessage) and message.tool_calls:
            return index
    return max(len(messages) - 1, 0)


def _shrink_tool_results(messages: list[AnyMessage], budget: int) -> list[AnyMessage]:
    """Share `budget` across the remaining tool results so an oversized turn still fits.

    One turn can carry several parallel tool calls whose results together outgrow the
    budget. Dropping any of them would leave the model unable to answer, so every result
    gives up the same share of its length instead.

    The share has no floor. A wide enough fan-out leaves each result too short to act on,
    but a floor applied to every result would put the prompt back over the cap, which is
    the failure this module exists to prevent. What the share cannot cover is the messages
    around the results: a request whose own tool calls fill the budget stays over it,
    because the only way under would be to drop the call the model is waiting on.
    """
    results = [message for message in messages if isinstance(message, ToolMessage)]
    if not results:
        return messages

    others = [message for message in messages if not isinstance(message, ToolMessage)]
    # The counter charges each result for its role and tool call id on top of its content,
    # so the share pays for those envelopes before it divides what is left.
    envelopes = sum(_token_count([message.model_copy(update={"content": ""})]) for message in results)
    share = max(0, (budget - _token_count(others) - envelopes) // len(results))
    return [_truncated_to(message, share) if isinstance(message, ToolMessage) else message for message in messages]


def trim_agent_messages(state: dict[str, Any]) -> dict[str, list[AnyMessage]]:
    """Return the message history to send to the model, capped and trimmed to budget."""
    messages: list[AnyMessage] = [
        _truncated_to(message, MAX_TOOL_RESULT_TOKENS) if isinstance(message, ToolMessage) else message
        for message in state["messages"]
    ]
    # Pin the opening request so the agent keeps its task even after a deep trim.
    pinned = messages[:1] if messages and isinstance(messages[0], HumanMessage) else []
    body = messages[len(pinned) :]
    pending = _pending_turn_start(body)
    counts = [_token_count([message]) for message in body]
    total = _token_count(pinned) + sum(counts)

    dropped = 0
    while dropped < pending and total > MAX_PROMPT_TOKENS:
        total -= counts[dropped]
        dropped += 1

    # A tool result whose request was dropped answers nothing, and providers reject it,
    # so drop the orphans the trim exposed. The pending turn opens on its own request,
    # which ends this loop before it can reach into that turn.
    while dropped < pending and isinstance(body[dropped], ToolMessage):
        total -= counts[dropped]
        dropped += 1

    kept: list[AnyMessage] = [*pinned, *body[dropped:]]
    if total > MAX_PROMPT_TOKENS:
        kept = _shrink_tool_results(kept, MAX_PROMPT_TOKENS)
    return {"llm_input_messages": kept}
