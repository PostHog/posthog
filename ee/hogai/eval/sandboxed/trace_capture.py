"""Capture sandboxed eval traces and evaluation events to PostHog.

Parses ACP JSONL session logs into Anthropic-format messages and emits
``$ai_trace``, ``$ai_generation``, ``$ai_span``, and ``$ai_evaluation``
events to a PostHog client (typically US production).
"""

from __future__ import annotations

import json
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any

from posthoganalytics import Posthog

from products.signals.eval.capture import deterministic_uuid

logger = logging.getLogger(__name__)

DISTINCT_ID = "llma_eval"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_PROVIDER = "anthropic"


# ---------------------------------------------------------------------------
# Parsed log structures
# ---------------------------------------------------------------------------


@dataclass
class SpanDescriptor:
    span_id: str
    span_name: str
    content: str = ""
    timestamp: str = ""


@dataclass
class ParsedLog:
    messages: list[dict[str, Any]] = field(default_factory=list)
    spans: list[SpanDescriptor] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    first_timestamp: str = ""
    last_timestamp: str = ""


# ---------------------------------------------------------------------------
# ACP JSONL → Anthropic messages + spans
# ---------------------------------------------------------------------------


def parse_log(raw_log: str) -> ParsedLog:
    """Parse an ACP JSONL log into Anthropic-format messages and span descriptors.

    Messages follow the Anthropic message format:
    - User messages: ``{role: "user", content: "..."}``
    - Assistant messages with tool calls: ``{role: "assistant", content: [{type: "text", ...}, {type: "tool_use", ...}]}``
    - Tool results: ``{role: "user", content: [{type: "tool_result", ...}]}``

    Non-AI events (console messages, errors) become span descriptors.
    """
    result = ParsedLog()
    # Accumulate content blocks for the current assistant message
    assistant_content: list[dict[str, Any]] = []
    # Track tool results to batch into a single user message
    pending_tool_results: list[dict[str, Any]] = []

    for line in raw_log.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts = entry.get("timestamp", "")
        if ts:
            if not result.first_timestamp:
                result.first_timestamp = ts
            result.last_timestamp = ts

        notification = entry.get("notification")
        if not isinstance(notification, dict):
            continue

        # Token usage from turn completion
        entry_result = notification.get("result")
        if isinstance(entry_result, dict):
            usage = entry_result.get("usage")
            if isinstance(usage, dict):
                result.token_usage = {
                    "inputTokens": usage.get("inputTokens", 0),
                    "outputTokens": usage.get("outputTokens", 0),
                    "cachedReadTokens": usage.get("cachedReadTokens", 0),
                    "totalTokens": usage.get("totalTokens", 0),
                }

        method = notification.get("method", "")

        # Non-AI events → spans
        if method == "_posthog/console":
            params = notification.get("params", {})
            level = params.get("level", "info")
            msg = params.get("message", "")
            if msg:
                result.spans.append(
                    SpanDescriptor(
                        span_id=str(uuid.uuid4()),
                        span_name=f"console/{level}",
                        content=msg[:2000],
                        timestamp=ts,
                    )
                )
            continue

        if method == "_posthog/error":
            params = notification.get("params", {})
            msg = params.get("message", "") if isinstance(params, dict) else str(params)
            result.spans.append(
                SpanDescriptor(
                    span_id=str(uuid.uuid4()),
                    span_name="error",
                    content=msg[:2000] if msg else "unknown error",
                    timestamp=ts,
                )
            )
            continue

        if method != "session/update":
            continue

        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue

        session_update = update.get("sessionUpdate", "")

        # --- User message ---
        if session_update == "user_message":
            # Flush any pending assistant content
            _flush_assistant(result.messages, assistant_content)
            assistant_content = []
            # Flush any pending tool results
            _flush_tool_results(result.messages, pending_tool_results)
            pending_tool_results = []

            text = _extract_text(update)
            if text:
                result.messages.append({"role": "user", "content": text})

        # --- Agent message (text block) ---
        elif session_update == "agent_message":
            # Flush pending tool results before a new assistant turn
            _flush_tool_results(result.messages, pending_tool_results)
            pending_tool_results = []

            text = _extract_text(update)
            if text:
                assistant_content.append({"type": "text", "text": text})

        # --- Tool call start ---
        elif session_update == "tool_call":
            meta = update.get("_meta", {})
            cc = meta.get("claudeCode", {}) if isinstance(meta, dict) else {}
            tool_name = cc.get("toolName", update.get("title", "unknown_tool"))
            tool_call_id = update.get("toolCallId", str(uuid.uuid4()))
            raw_input = update.get("rawInput", {})

            assistant_content.append(
                {
                    "type": "tool_use",
                    "id": tool_call_id,
                    "name": tool_name,
                    "input": raw_input if isinstance(raw_input, dict) else {},
                }
            )

        # --- Tool call update (may contain result) ---
        elif session_update == "tool_call_update":
            status = update.get("status", "")
            tool_call_id = update.get("toolCallId", "")

            if status in ("completed", "failed", "error") and tool_call_id:
                # Flush the current assistant message (tool_use blocks) before adding tool_result
                _flush_assistant(result.messages, assistant_content)
                assistant_content = []

                raw_output = update.get("rawOutput", "")
                content = _extract_text(update)
                output_text = raw_output if raw_output else (content or "")
                if isinstance(output_text, dict):
                    output_text = json.dumps(output_text)

                is_error = status in ("failed", "error")
                tool_result: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": str(output_text)[:5000] if output_text else "(no output)",
                }
                if is_error:
                    tool_result["is_error"] = True
                pending_tool_results.append(tool_result)

        # Skip agent_message_chunk, agent_thought_chunk, usage_update, available_commands_update

    # Flush remaining
    _flush_tool_results(result.messages, pending_tool_results)
    _flush_assistant(result.messages, assistant_content)

    return result


def _flush_assistant(messages: list[dict], content_blocks: list[dict]) -> None:
    if content_blocks:
        messages.append({"role": "assistant", "content": list(content_blocks)})
        content_blocks.clear()


def _flush_tool_results(messages: list[dict], tool_results: list[dict]) -> None:
    if tool_results:
        messages.append({"role": "user", "content": list(tool_results)})
        tool_results.clear()


def _extract_text(update: dict) -> str:
    content = update.get("content")
    if isinstance(content, dict) and content.get("type") == "text":
        return content.get("text", "").strip()
    if isinstance(content, str):
        return content.strip()
    message = update.get("message")
    if isinstance(message, str):
        return message.strip()
    return ""


# ---------------------------------------------------------------------------
# Emit trace events to PostHog
# ---------------------------------------------------------------------------


def emit_trace_events(
    client: Posthog,
    trace_id: str,
    case_name: str,
    prompt: str,
    raw_log: str,
    duration: float,
    artifacts_summary: dict[str, Any] | None = None,
) -> None:
    """Parse an ACP log and emit ``$ai_generation``, ``$ai_span``, and ``$ai_trace`` events."""
    parsed = parse_log(raw_log)

    generation_id = str(uuid.uuid4())

    # $ai_generation — full conversation in Anthropic message format
    last_assistant_content = _get_last_assistant_content(parsed.messages)
    gen_properties: dict[str, Any] = {
        "$ai_trace_id": trace_id,
        "$ai_span_id": generation_id,
        "$ai_parent_id": trace_id,
        "$ai_model": DEFAULT_MODEL,
        "$ai_provider": DEFAULT_PROVIDER,
        "$ai_input": parsed.messages,
        "$ai_latency": duration,
    }
    if last_assistant_content is not None:
        gen_properties["$ai_output_choices"] = [{"message": {"role": "assistant", "content": last_assistant_content}}]
    if parsed.token_usage:
        gen_properties["$ai_input_tokens"] = parsed.token_usage.get("inputTokens", 0)
        gen_properties["$ai_output_tokens"] = parsed.token_usage.get("outputTokens", 0)
        gen_properties["$ai_cache_read_input_tokens"] = parsed.token_usage.get("cachedReadTokens", 0)

    client.capture(distinct_id=DISTINCT_ID, event="$ai_generation", properties=gen_properties)

    # $ai_span — non-AI events (console, errors)
    for span in parsed.spans:
        client.capture(
            distinct_id=DISTINCT_ID,
            event="$ai_span",
            properties={
                "$ai_trace_id": trace_id,
                "$ai_span_id": span.span_id,
                "$ai_parent_id": trace_id,
                "$ai_span_name": span.span_name,
                "$ai_output_state": span.content,
            },
        )

    # $ai_trace — root container (emitted last per convention)
    trace_properties: dict[str, Any] = {
        "$ai_trace_id": trace_id,
        "$ai_trace_name": case_name,
        "$ai_latency": duration,
    }
    if prompt:
        trace_properties["$ai_input_state"] = json.dumps({"prompt": prompt[:5000]})
    if artifacts_summary:
        trace_properties["$ai_output_state"] = json.dumps(artifacts_summary)[:10000]

    client.capture(distinct_id=DISTINCT_ID, event="$ai_trace", properties=trace_properties)

    logger.info(
        "Emitted trace events for '%s' (trace=%s): 1 generation, %d spans",
        case_name,
        trace_id,
        len(parsed.spans),
    )


def _get_last_assistant_content(messages: list[dict]) -> Any | None:
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            return msg.get("content")
    return None


# ---------------------------------------------------------------------------
# Emit evaluation events to PostHog
# ---------------------------------------------------------------------------


def emit_evaluation_events(
    client: Posthog,
    experiment_name: str,
    eval_results: list,
) -> str:
    """Emit ``$ai_evaluation`` events for each scorer result in each eval case.

    Returns the deterministic experiment_id (for building dashboard URLs).
    """
    experiment_id = deterministic_uuid(f"sandboxed-{experiment_name}")
    formatted_name = f"sandboxed-agent/{experiment_name}"

    for result in eval_results:
        case_name = result.input.get("name", "unknown") if isinstance(result.input, dict) else "unknown"
        trace_id = result.metadata.get("trace_id") if result.metadata else None
        item_id = deterministic_uuid(f"{experiment_name}/{case_name}")

        output_summary = result.output
        expected_summary = result.expected

        for scorer_name, score_value in (result.scores or {}).items():
            properties: dict[str, Any] = {
                "$ai_eval_source": "sandboxed-agent",
                "$ai_evaluation_type": "offline",
                "$ai_experiment_id": experiment_id,
                "$ai_experiment_name": formatted_name,
                "$ai_experiment_item_id": item_id,
                "$ai_experiment_item_name": case_name,
                "$ai_metric_name": scorer_name,
                "$ai_metric_version": "1",
                "$ai_result_type": "numeric",
                "$ai_score_min": 0,
                "$ai_score_max": 1,
                "$ai_status": "ok" if score_value is not None else "error",
            }
            if score_value is not None:
                properties["$ai_score"] = score_value
            if trace_id:
                properties["$ai_trace_id"] = trace_id
            if isinstance(result.input, dict):
                prompt = result.input.get("prompt", "")
                if prompt:
                    properties["$ai_input"] = str(prompt)[:10000]
            if output_summary is not None:
                properties["$ai_output"] = str(output_summary)[:10000]
            if expected_summary is not None:
                properties["$ai_expected"] = str(expected_summary)[:10000]

            client.capture(distinct_id=DISTINCT_ID, event="$ai_evaluation", properties=properties)

    logger.info(
        "Emitted evaluation events for experiment '%s' (%d results)",
        experiment_name,
        len(eval_results),
    )
    return experiment_id
