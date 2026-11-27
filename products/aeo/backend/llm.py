"""Ask Claude, through the AI gateway, for a JSON answer after it researches with web search.

Prompt and keyword suggestions both make this call. Each caller turns failures into its own message.
"""

from __future__ import annotations

import json
import time
import unicodedata
from typing import Any

from django.conf import settings

import requests

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import AIGatewayConfig

from products.aeo.backend.engines import (
    ANTHROPIC_WEB_SEARCH_TOOL_TYPE,
    gateway_request_headers,
    raise_for_gateway_status,
)

CALL_TIMEOUT_SECONDS = 120
# A call with less time than this left would only time out, so the job stops as too slow instead.
MIN_CALL_SECONDS = 15
# Web search can pause a turn (`pause_turn`); each continuation is another call, all under one deadline.
MAX_CONTINUATIONS = 3
DEADLINE_SECONDS = 300
MAX_JSON_START_ATTEMPTS = 50


class UnreadableAnswerError(Exception):
    pass


@frozen
class ClaudeAnswer:
    text: str
    stop_reason: str | None


def ask_with_web_search(
    gateway: AIGatewayConfig,
    instructions: str,
    *,
    team_id: int,
    trace_id: str,
    aeo_feature: str,
    max_tokens: int,
    max_searches: int,
    deadline: float | None = None,
    model: str | None = None,
) -> ClaudeAnswer | None:
    """Claude's final answer, or None when the deadline (a `time.monotonic()` value, DEADLINE_SECONDS from now
    by default) passes first. Raises `requests.RequestException` or `ValueError` when a call fails, and
    `AICreditsExhausted` when the gateway refuses the team for lack of AI credits. An answer cut off by the token
    limit keeps its complete items."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": instructions}]
    headers = gateway_request_headers(
        gateway,
        trace_id=trace_id,
        properties={"team_id": str(team_id), "aeo_feature": aeo_feature},
        anthropic=True,
    )
    if deadline is None:
        deadline = time.monotonic() + DEADLINE_SECONDS
    assistant_content: list[Any] = []
    with requests.Session() as session:
        # Keep the in-cluster gateway call off any egress proxy, as the engines do.
        session.trust_env = False
        for _ in range(MAX_CONTINUATIONS + 1):
            remaining = deadline - time.monotonic()
            if remaining < MIN_CALL_SECONDS:
                break
            response = session.post(
                gateway.url.rstrip("/") + "/messages",
                headers=headers,
                json={
                    "model": model or settings.AEO_ANTHROPIC_MODEL,
                    "max_tokens": max_tokens,
                    "messages": messages,
                    "tools": [
                        {
                            "type": ANTHROPIC_WEB_SEARCH_TOOL_TYPE,
                            "name": "web_search",
                            "max_uses": max_searches,
                            "allowed_callers": ["direct"],
                        }
                    ],
                },
                timeout=min(CALL_TIMEOUT_SECONDS, remaining),
            )
            raise_for_gateway_status(response)
            body = response.json()
            if body.get("stop_reason") != "pause_turn":
                text = _answer_text(body)
                if body.get("stop_reason") == "max_tokens":
                    # Keep the complete items instead of losing the whole paid answer.
                    text = _complete_items_prefix(text)
                return ClaudeAnswer(text=text, stop_reason=body.get("stop_reason"))
            # A paused turn resumes when all of the assistant's content so far is sent back as is.
            assistant_content = [*assistant_content, *(body.get("content") or [])]
            messages = [messages[0], {"role": "assistant", "content": assistant_content}]
    return None


def answer_items(text: str) -> list[Any]:
    """The JSON array of items in the answer. Commentary can come before it and carry
    brackets of its own, such as a markdown link, so each `[` is tried until one decodes to a list holding objects.
    A bare empty array is a valid answer with nothing to suggest. Raises UnreadableAnswerError without one."""
    decoder = json.JSONDecoder()
    found_empty = False
    for start in (i for i, char in enumerate(text) if char == "["):
        try:
            items, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(items, list) and any(isinstance(item, dict) for item in items):
            return items
        found_empty = found_empty or items == []
    if found_empty:
        return []
    raise UnreadableAnswerError()


def visible(text: str) -> str:
    return "".join(char for char in text if unicodedata.category(char) not in ("Cf", "Cc") or char.isspace())


def _complete_items_prefix(text: str) -> str:
    end = text.rfind("}")
    if end == -1:
        return text
    prefix = text[: end + 1]
    # Commentary before the JSON can carry brackets of its own, so each opening bracket is tried as the start
    # until the closed text decodes. The attempts are capped because each one scans the rest of the answer.
    starts = [i for i, char in enumerate(prefix) if char in "[{"][:MAX_JSON_START_ATTEMPTS]
    for start in starts:
        closers = _unclosed_brackets(prefix, start)
        if closers is None:
            continue
        try:
            json.loads(prefix[start:] + closers)
        except json.JSONDecodeError:
            continue
        return prefix + closers
    return prefix + "]"


def _unclosed_brackets(text: str, start: int) -> str | None:
    closers: list[str] = []
    in_string = False
    escaped = False
    for char in text[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            closers.append("]" if char == "[" else "}")
        elif char in "]}":
            if not closers or closers.pop() != char:
                return None
    if in_string:
        return None
    return "".join(reversed(closers))


def _answer_text(body: dict[str, Any]) -> str:
    return "".join(
        block.get("text", "")
        for block in body.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    )
