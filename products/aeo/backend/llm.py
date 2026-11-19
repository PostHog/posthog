"""Ask Claude, through the AI gateway, for a JSON array after it researches with web search.

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
from posthog.llm.gateway_client import AIGatewayConfig, ai_gateway_headers

from products.aeo.backend.engines import ANTHROPIC_WEB_SEARCH_TOOL_TYPE

CALL_TIMEOUT_SECONDS = 120
# A call with less time than this left would only time out, so the job stops as too slow instead.
MIN_CALL_SECONDS = 15
# Web search can pause a turn (`pause_turn`); each continuation is another call, all under one deadline.
MAX_CONTINUATIONS = 3
DEADLINE_SECONDS = 300


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
) -> ClaudeAnswer | None:
    """Claude's final answer, or None when the deadline passes first. Raises `requests.RequestException`
    or `ValueError` when a call fails. An answer cut off by the token limit keeps its complete items."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": instructions}]
    headers = {
        "Authorization": f"Bearer {gateway.api_key}",
        "anthropic-version": "2023-06-01",
        **(
            ai_gateway_headers(trace_id=trace_id, properties={"team_id": str(team_id), "aeo_feature": aeo_feature})
            or {}
        ),
    }
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
                    "model": settings.AEO_ANTHROPIC_MODEL,
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
            response.raise_for_status()
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
    """Close an array the token limit cut off after its last complete object."""
    end = text.rfind("}")
    return text[: end + 1] + "]" if end != -1 else text


def _answer_text(body: dict[str, Any]) -> str:
    return "".join(
        block.get("text", "")
        for block in body.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    )
