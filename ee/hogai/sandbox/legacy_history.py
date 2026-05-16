"""Format a Conversation's prior turns as a text block for sandbox handoff.

When a user continues a LangGraph-era conversation under sandbox mode, the
sandboxed agent has no checkpoint state to load from. Instead, we render the
prior turns as a compact transcript wrapped in
``<previous_conversation>…</previous_conversation>`` tags and prepend it to the
first user message of the new sandbox run.

Source priority:

1. ``Conversation.messages_json`` — populated by ``_persist_sandbox_turn`` and
   by some non-LangGraph paths. Fast, no LangGraph imports needed.
2. The LangGraph checkpoint, fetched via ``AssistantGraph(...).aget_state(...)``.
   Heavier, lazy-imported.

The output is capped at ``MAX_HISTORY_CHARS``; the oldest turns are dropped
first to keep recent context.
"""

from __future__ import annotations

from typing import Any

import structlog

from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)

MAX_HISTORY_CHARS = 50_000
WRAPPER_OPEN = "<previous_conversation>"
WRAPPER_CLOSE = "</previous_conversation>"
WRAPPER_INSTRUCTIONS = (
    "The user is continuing a previous PostHog AI conversation that ran on the legacy "
    "agent. Use the transcript below as background only — do not echo it back, do not "
    "re-execute the prior tool calls, and treat the user's new message as the active "
    "request."
)


def _truncate_to_limit(turns: list[str], limit: int) -> list[str]:
    """Drop oldest turns until the rendered total fits within ``limit`` chars."""
    while turns and sum(len(t) for t in turns) + len(WRAPPER_OPEN) + len(WRAPPER_CLOSE) > limit:
        turns.pop(0)
    return turns


def _render_message_from_json(message: dict[str, Any]) -> str | None:
    """Render a single ``messages_json`` entry as a labeled transcript turn.

    The serializer in ``ee/hogai/api/serializers.py`` already drops `_meta`
    sentinels, so any caller that passes those will be ignored here.
    """
    if not isinstance(message, dict):
        return None
    if "_meta" in message and len(message) == 1:
        return None

    mtype = message.get("type")
    content = message.get("content")
    if isinstance(content, list):
        # Multi-part content (e.g. tool calls). Pull text parts only.
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        content_text = "\n".join(t for t in text_parts if t)
    elif isinstance(content, str):
        content_text = content
    else:
        content_text = ""

    content_text = content_text.strip()
    if not content_text:
        return None

    if mtype == "human":
        return f"User: {content_text}"
    if mtype in {"ai", "assistant", "ai/assistant"}:
        return f"PostHog AI: {content_text}"
    if mtype == "ai/failure":
        return f"PostHog AI (error): {content_text}"
    # Skip context/tool/system messages — they would only confuse the new agent.
    return None


def _format_from_messages_json(messages_json: list[Any]) -> str | None:
    rendered: list[str] = []
    for message in messages_json:
        line = _render_message_from_json(message)
        if line:
            rendered.append(line)
    if not rendered:
        return None
    rendered = _truncate_to_limit(rendered, MAX_HISTORY_CHARS)
    return _wrap(rendered)


def _wrap(turns: list[str]) -> str:
    body = "\n\n".join(turns)
    return f"{WRAPPER_OPEN}\n{WRAPPER_INSTRUCTIONS}\n\n{body}\n{WRAPPER_CLOSE}"


def _format_from_langgraph_state(conversation: Conversation) -> str | None:
    """Fall back to fetching the LangGraph checkpoint when ``messages_json`` is empty.

    Imports are local to keep this module lightweight when the LangGraph stack
    is uninvolved (e.g. when the conversation is brand new).
    """
    try:
        from asgiref.sync import async_to_sync as _sync

        from ee.hogai.api.serializers import CONVERSATION_TYPE_MAP

        graph_class, state_class = CONVERSATION_TYPE_MAP.get(conversation.type, (None, None))
        if graph_class is None or state_class is None:
            return None
        graph = graph_class(conversation.team, conversation.user).compile_full_graph()

        async def _fetch() -> Any:
            return await graph.aget_state({"configurable": {"thread_id": str(conversation.id), "checkpoint_ns": ""}})

        snapshot = _sync(_fetch)()
    except Exception:
        logger.warning("legacy_history_langgraph_state_failed", exc_info=True)
        return None

    if not snapshot or not snapshot.values:
        return None
    try:
        state = state_class.model_validate(snapshot.values)
    except Exception:
        logger.warning("legacy_history_state_validate_failed", exc_info=True)
        return None

    messages = list(getattr(state, "messages", []) or [])
    if not messages:
        return None

    rendered: list[str] = []
    for message in messages:
        line = _render_message_from_json(message.model_dump() if hasattr(message, "model_dump") else dict(message))
        if line:
            rendered.append(line)
    if not rendered:
        return None
    rendered = _truncate_to_limit(rendered, MAX_HISTORY_CHARS)
    return _wrap(rendered)


def format_legacy_history_for_sandbox(conversation: Conversation) -> str | None:
    """Return a ``<previous_conversation>…</previous_conversation>`` block or ``None``.

    Designed to be cheap on the common path (no prior turns to render) and to
    fail closed — any exception inside falls back to ``None`` so the sandbox
    run can still proceed without history context.
    """
    # New conversations or conversations that already have a live sandbox run
    # don't need legacy history.
    if conversation.sandbox_task_id is not None:
        return None

    messages_json = conversation.messages_json or []
    if messages_json:
        try:
            text = _format_from_messages_json(messages_json)
        except Exception:
            logger.warning("legacy_history_messages_json_failed", exc_info=True)
            text = None
        if text:
            return text

    return _format_from_langgraph_state(conversation)


__all__ = ["format_legacy_history_for_sandbox"]
