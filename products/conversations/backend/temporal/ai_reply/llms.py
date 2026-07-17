from __future__ import annotations

from typing import Any

from anthropic import APIError
from temporalio.exceptions import ApplicationError

from products.conversations.backend.temporal.ai_reply.constants import LLM_REQUEST_TIMEOUT_SECONDS


def anthropic_text(message: Any) -> str:
    """Concatenate the text blocks of an Anthropic Messages response."""
    return "".join(block.text for block in message.content if getattr(block, "type", None) == "text")


def tracing_kwargs(trace_id: str, ticket_id: str) -> dict[str, Any]:
    """Per-ticket gateway attribution to splat into a `create_message(...)` call.

    `metadata.user_id` becomes the generation's `$ai_trace_id` (so every utility call for one
    ticket shares a trace), and `x-posthog-property-ticket_id` is merged into the captured
    `$ai_generation` properties. Each key is omitted when its value is empty so we never send a
    null metadata/header; add another tracing property here and all callers pick it up.
    """
    kwargs: dict[str, Any] = {}
    if trace_id:
        kwargs["metadata"] = {"user_id": trace_id}
    if ticket_id:
        kwargs["extra_headers"] = {"x-posthog-property-ticket_id": ticket_id}
    return kwargs


async def create_message(client: Any, **kwargs: Any) -> Any:
    """Call the gateway Messages API with a bounded timeout, re-raising transient API errors
    as compact ApplicationErrors.

    The raw anthropic exception (e.g. APITimeoutError) carries a huge stack trace plus a nested
    cause; serialized into a Temporal Failure it overflows the per-failure payload size limit,
    so the real error is replaced with "Failure exceeds size limit." in history. Raising a small
    ApplicationError (with `from None` to drop the giant chained cause) keeps the failure storable
    and still retryable by the activity's retry policy.

    Deterministic 4xx (e.g. a model rejected by the gateway allowlist, a malformed request) are
    marked non_retryable: retrying can't fix them, so fail fast instead of burning the policy's
    attempts. Transient errors (timeouts, dropped connections, 408/409/429, 5xx) stay retryable.
    """
    try:
        return await client.messages.create(timeout=LLM_REQUEST_TIMEOUT_SECONDS, **kwargs)
    except APIError as e:
        status = getattr(e, "status_code", None)
        non_retryable = status is not None and 400 <= status < 500 and status not in (408, 409, 429)
        raise ApplicationError(
            f"LLM gateway request failed: {type(e).__name__}" + (f" ({status})" if status else ""),
            type=type(e).__name__,
            non_retryable=non_retryable,
        ) from None


def strip_json_fence(text: str) -> str:
    """Strip a leading/trailing markdown code fence (```json ... ```) the LLM may wrap JSON in."""
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        close = s.rfind("```")
        if close != -1:
            s = s[:close]
    return s.strip()
