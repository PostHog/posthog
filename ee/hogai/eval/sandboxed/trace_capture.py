"""Capture sandboxed eval traces and evaluation events to PostHog.

Parses ACP JSONL session logs into per-turn Anthropic-format generations
and emits ``$ai_trace``, ``$ai_generation``, ``$ai_span``, and
``$ai_evaluation`` events to a PostHog client (typically US production).

Scorer LLM calls are also traced: each scorer invocation gets its own
``$ai_trace_id`` so evaluation events link to the scorer's reasoning.
"""

from __future__ import annotations

import json
import uuid
import logging
from collections.abc import Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from braintrust_core.score import Scorer
from posthoganalytics import Posthog

logger = logging.getLogger(__name__)

DISTINCT_ID = "llma_eval"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_PROVIDER = "anthropic"

# Context var for injecting per-scorer-invocation trace properties
# into the traced OpenAI client's ``create()`` calls.
_scorer_context: ContextVar[dict[str, Any] | None] = ContextVar("_scorer_context", default=None)


@dataclass
class GenerationDescriptor:
    """One model turn: full conversation history → assistant response."""

    input_messages: list[dict[str, Any]] = field(default_factory=list)
    output_content: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    timestamp: str = ""
    """Timestamp of the first output block in this generation (for chronological ordering)."""

    start_ts: str = ""
    """When this model call was invoked — session prompt time for the first gen,
    the last tool_result completion time for subsequent gens."""

    end_ts: str = ""
    """Timestamp of the last output block added to this generation — approximates
    when the model's streaming response finished."""


@dataclass
class SpanDescriptor:
    span_id: str
    span_name: str
    content: str = ""
    timestamp: str = ""


@dataclass
class ParsedLog:
    generations: list[GenerationDescriptor] = field(default_factory=list)
    spans: list[SpanDescriptor] = field(default_factory=list)
    first_timestamp: str = ""
    last_timestamp: str = ""

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Flat Anthropic message list (for Braintrust compatibility).

        Uses the last generation's input (full history) plus its output
        to reconstruct the complete conversation.
        """
        if not self.generations:
            return []
        last = self.generations[-1]
        msgs = list(last.input_messages)
        if last.output_content:
            msgs.append({"role": "assistant", "content": list(last.output_content)})
        return msgs

    @property
    def total_token_usage(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for gen in self.generations:
            for k, v in gen.token_usage.items():
                total[k] = total.get(k, 0) + v
        return total


class AcpLogParser:
    """Single-use parser for an ACP JSONL session log.

    Holds all state that accumulates as the parser walks the log, dispatches
    each line to a handler method based on notification method and session
    update kind, and returns a populated ``ParsedLog``.

    Each generation represents one model API call with the full accumulated
    conversation history as input (matching how autoregressive LLMs work).
    Generation boundaries are detected when a new ``agent_message`` or
    ``tool_call`` arrives after tool results have been collected — that
    signals the model received the tool results and is producing a new
    response.
    """

    def __init__(self, initial_prompt: str = ""):
        self._result = ParsedLog()

        # Full conversation history — grows with each generation.
        # Seed with the initial prompt (not present in the ACP log).
        self._history: list[dict[str, Any]] = []
        if initial_prompt:
            self._history.append({"role": "user", "content": initial_prompt})

        # State for the current generation being built
        self._current_output: list[dict[str, Any]] = []
        self._pending_tool_results: list[dict[str, Any]] = []
        self._last_token_usage: dict[str, int] = {}
        self._gen_timestamp: str = ""
        self._gen_start_ts: str = ""  # When the model call was invoked
        self._gen_last_output_ts: str = ""  # Timestamp of most recent output block
        self._last_tool_result_ts: str = ""  # Drives next gen's start_ts

    def parse(self, raw_log: str) -> ParsedLog:
        for line in raw_log.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_entry(entry)

        # Flush anything remaining (e.g. if end_turn was missing)
        self._drain_pending_tool_results_into_history()
        self._flush_generation()
        return self._result

    def _handle_entry(self, entry: dict) -> None:
        ts = entry.get("timestamp", "")
        if ts:
            if not self._result.first_timestamp:
                self._result.first_timestamp = ts
            self._result.last_timestamp = ts

        notification = entry.get("notification")
        if not isinstance(notification, dict):
            return

        # Capture the session/prompt timestamp as the start of the first model call
        # (orchestrator sends the prompt; the model starts processing it).
        method = notification.get("method", "")
        if method == "session/prompt" and ts and not self._gen_start_ts:
            self._gen_start_ts = ts

        # Token usage + end_turn completion
        entry_result = notification.get("result")
        if isinstance(entry_result, dict):
            if self._handle_result(entry_result):
                return  # end_turn consumed this entry

        if method == "_posthog/console":
            self._on_console(notification, ts)
            return
        if method == "_posthog/error":
            self._on_error(notification, ts)
            return
        if method != "session/update":
            return

        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if isinstance(update, dict):
            self._dispatch_session_update(update, ts)

    def _handle_result(self, entry_result: dict) -> bool:
        """Process token usage and end_turn. Returns True if end_turn was handled."""
        usage = entry_result.get("usage")
        if isinstance(usage, dict):
            self._last_token_usage = {
                "inputTokens": usage.get("inputTokens", 0),
                "outputTokens": usage.get("outputTokens", 0),
                "cachedReadTokens": usage.get("cachedReadTokens", 0),
                "cachedWriteTokens": usage.get("cachedWriteTokens", 0),
                "totalTokens": usage.get("totalTokens", 0),
            }
        if entry_result.get("stopReason") == "end_turn":
            self._flush_generation(token_usage=self._last_token_usage)
            self._last_token_usage = {}
            return True
        return False

    def _on_console(self, notification: dict, ts: str) -> None:
        params = notification.get("params", {}) or {}
        level = params.get("level", "info")
        msg = params.get("message", "")
        if not msg:
            return
        self._result.spans.append(
            SpanDescriptor(
                span_id=str(uuid.uuid4()),
                span_name=f"console/{level}",
                content=msg,
                timestamp=ts,
            )
        )

    def _on_error(self, notification: dict, ts: str) -> None:
        params = notification.get("params", {})
        msg = params.get("message", "") if isinstance(params, dict) else str(params)
        self._result.spans.append(
            SpanDescriptor(
                span_id=str(uuid.uuid4()),
                span_name="error",
                content=msg or "unknown error",
                timestamp=ts,
            )
        )

    def _dispatch_session_update(self, update: dict, ts: str) -> None:
        kind = update.get("sessionUpdate", "")
        handler = self._SESSION_UPDATE_HANDLERS.get(kind)
        if handler is not None:
            handler(self, update, ts)
        # Intentionally ignored: agent_message_chunk, agent_thought_chunk,
        # usage_update, available_commands_update, etc.

    def _on_user_message(self, update: dict, _ts: str) -> None:
        self._flush_generation()
        self._drain_pending_tool_results_into_history()
        text = self._extract_text(update)
        if text:
            self._history.append({"role": "user", "content": text})

    def _on_agent_message(self, update: dict, ts: str) -> None:
        # If tool results are pending, the model has received them and is
        # producing a new response — flush the previous generation first.
        self._flush_for_new_turn_if_pending()

        if not self._gen_timestamp:
            self._gen_timestamp = ts
        text = self._extract_text(update)
        if text:
            self._current_output.append({"type": "text", "text": text})
            self._gen_last_output_ts = ts

    def _on_tool_call(self, update: dict, ts: str) -> None:
        # A new tool_call with pending tool_results means the previous model call
        # finished (with just its tool_use output, no text), tools ran, and now a
        # new model call has produced this next tool_use. Flush the previous gen.
        self._flush_for_new_turn_if_pending()

        if not self._gen_timestamp:
            self._gen_timestamp = ts
        meta = update.get("_meta", {})
        cc = meta.get("claudeCode", {}) if isinstance(meta, dict) else {}
        tool_name = cc.get("toolName", update.get("title", "unknown_tool"))
        tool_call_id = update.get("toolCallId", str(uuid.uuid4()))
        raw_input = update.get("rawInput", {})

        self._current_output.append(
            {
                "type": "tool_use",
                "id": tool_call_id,
                "name": tool_name,
                "input": raw_input if isinstance(raw_input, dict) else {},
            }
        )
        self._gen_last_output_ts = ts

    def _on_tool_call_update(self, update: dict, ts: str) -> None:
        tool_call_id = update.get("toolCallId", "")

        # ACP streams the tool input in a follow-up update, not the initial tool_call.
        # Patch the matching tool_use block so $ai_output_choices carries real args.
        late_input = update.get("rawInput")
        if isinstance(late_input, dict) and late_input and tool_call_id:
            for block in self._current_output:
                if block.get("type") == "tool_use" and block.get("id") == tool_call_id:
                    block["input"] = late_input
                    break

        status = update.get("status", "")
        if status not in ("completed", "failed", "error") or not tool_call_id:
            return

        raw_output = update.get("rawOutput", "")
        content = self._extract_text(update)
        output_text = raw_output if raw_output else (content or "")
        if isinstance(output_text, dict):
            output_text = json.dumps(output_text)

        tool_result: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": str(output_text) if output_text else "(no output)",
        }
        if status in ("failed", "error"):
            tool_result["is_error"] = True
        self._pending_tool_results.append(tool_result)
        if ts:
            self._last_tool_result_ts = ts

    _SESSION_UPDATE_HANDLERS = {
        "user_message": _on_user_message,
        "agent_message": _on_agent_message,
        "tool_call": _on_tool_call,
        "tool_call_update": _on_tool_call_update,
    }

    def _flush_for_new_turn_if_pending(self) -> None:
        """If we have queued tool_results, we're starting a new model call:
        flush the previous generation, append the tool_results as a user
        message in history, and set the next generation's start_ts."""
        if not self._pending_tool_results:
            return
        self._flush_generation()
        self._history.append({"role": "user", "content": list(self._pending_tool_results)})
        self._pending_tool_results = []
        self._gen_start_ts = self._last_tool_result_ts

    def _drain_pending_tool_results_into_history(self) -> None:
        if self._pending_tool_results:
            self._history.append({"role": "user", "content": list(self._pending_tool_results)})
            self._pending_tool_results = []

    def _flush_generation(self, token_usage: dict[str, int] | None = None) -> None:
        """Flush accumulated output into a GenerationDescriptor with full history as input."""
        if not self._current_output:
            return
        self._result.generations.append(
            GenerationDescriptor(
                input_messages=list(self._history),
                output_content=list(self._current_output),
                token_usage=token_usage or {},
                timestamp=self._gen_timestamp,
                start_ts=self._gen_start_ts,
                end_ts=self._gen_last_output_ts or self._gen_timestamp,
            )
        )
        # Add the assistant response to history for the next generation
        self._history.append({"role": "assistant", "content": list(self._current_output)})
        self._current_output = []
        self._gen_timestamp = ""
        self._gen_start_ts = ""
        self._gen_last_output_ts = ""

    @staticmethod
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


def parse_log(raw_log: str, initial_prompt: str = "") -> ParsedLog:
    """Parse an ACP JSONL log into per-turn generations and span descriptors.

    ``initial_prompt`` is injected as the first user message because the
    agent-server's ``sendInitialTaskMessage`` doesn't emit a ``user_message``
    session update in the ACP log.
    """
    return AcpLogParser(initial_prompt=initial_prompt).parse(raw_log)


def _build_posthog_kwargs() -> dict[str, Any]:
    """Build PostHog tracing kwargs from the current scorer context var.

    Sets both ``posthog_trace_id`` (direct kwarg, prevents the SDK from
    generating its own trace_id) and ``$ai_trace_id`` / ``$ai_parent_id``
    in ``posthog_properties`` (for the actual event properties).
    """
    ctx = _scorer_context.get()
    if not ctx:
        return {}
    trace_id = ctx["trace_id"]
    return {
        "posthog_distinct_id": DISTINCT_ID,
        "posthog_trace_id": trace_id,
        "posthog_properties": {
            "$ai_trace_id": trace_id,
            "$ai_parent_id": trace_id,
            "$ai_span_name": "Scorer",
            "ai_product": "evals",
            "$ai_experiment_id": ctx.get("experiment_id", ""),
            "$ai_experiment_name": ctx.get("experiment_name", ""),
        },
    }


@dataclass
class TracedClients:
    """Holds traced OpenAI and Anthropic clients for scorer LLM calls."""

    openai_llm_client: Any  # autoevals LLMClient
    anthropic_client: Any  # posthoganalytics AsyncAnthropic


def create_traced_scorer_clients(posthog_client: Posthog) -> TracedClients:
    """Create OpenAI and Anthropic clients that trace LLM calls to PostHog.

    Uses a context var (``_scorer_context``) to inject per-invocation
    trace properties into each ``create()`` call.
    """
    from autoevals.oai import LLMClient
    from openai import RateLimitError
    from posthoganalytics.ai.anthropic import AsyncAnthropic
    from posthoganalytics.ai.openai import AsyncOpenAI

    # --- Traced OpenAI client (for autoevals LLMClassifier scorers) ---
    openai_client = AsyncOpenAI(posthog_client=posthog_client)
    original_openai_create = openai_client.chat.completions.create

    async def patched_openai_create(*args, **kwargs):
        for k, v in _build_posthog_kwargs().items():
            kwargs.setdefault(k, v)
        return await original_openai_create(*args, **kwargs)

    openai_client.chat.completions.create = patched_openai_create  # type: ignore

    class _TracedLLMClient(LLMClient):
        def __post_init__(self):
            pass  # Skip Braintrust wrapping

    openai_llm_client = _TracedLLMClient(
        openai=openai_client,
        complete=patched_openai_create,
        embed=openai_client.embeddings.create,
        moderation=openai_client.moderations.create,
        is_async=True,
        RateLimitError=RateLimitError,
    )

    # --- Traced Anthropic client ---
    anthropic_client = AsyncAnthropic(posthog_client=posthog_client)
    original_anthropic_create = anthropic_client.messages.create

    async def patched_anthropic_create(*args, **kwargs):
        for k, v in _build_posthog_kwargs().items():
            kwargs.setdefault(k, v)
        return await original_anthropic_create(*args, **kwargs)

    anthropic_client.messages.create = patched_anthropic_create  # type: ignore

    return TracedClients(
        openai_llm_client=openai_llm_client,
        anthropic_client=anthropic_client,
    )


class TracedScorer(Scorer):
    """Wraps a Scorer to trace LLM calls and collect per-invocation trace IDs.

    For LLM-based scorers (those with a ``client`` attribute), injects a
    PostHog-traced OpenAI client. For all scorers, generates a trace_id
    per invocation and stores it in ``scorer_traces`` for later use in
    ``$ai_evaluation`` events.
    """

    def __init__(
        self,
        inner: Scorer,
        traced_clients: TracedClients,
        eval_metadata: dict[str, Any],
        scorer_traces: dict[tuple[str, str], str],
        posthog_client: Posthog | None = None,
        agent_trace_id_lookup: dict[str, str] | None = None,
    ):
        self._inner = inner
        self._traced_clients = traced_clients
        self._eval_metadata = eval_metadata
        self._scorer_traces = scorer_traces
        self._posthog_client = posthog_client
        self._agent_trace_id_lookup = agent_trace_id_lookup if agent_trace_id_lookup is not None else {}

    def _name(self) -> str:
        return self._inner._name()

    @contextmanager
    def _invocation_context(self, case_name: str):
        """Patch traced clients onto the inner scorer and set the scorer trace context.

        Yields ``is_llm_scorer`` so the caller knows whether to emit a span.
        Restores the original client attributes and context var on exit.
        """
        has_client = hasattr(self._inner, "client")
        has_anthropic = hasattr(self._inner, "anthropic_client")
        is_llm_scorer = has_client or has_anthropic

        scorer_trace_id = str(uuid.uuid4()) if is_llm_scorer else None
        if scorer_trace_id:
            self._scorer_traces[(case_name, self._name())] = scorer_trace_id

        original_client = getattr(self._inner, "client", None) if has_client else None
        if has_client:
            self._inner.client = self._traced_clients.openai_llm_client

        original_anthropic = getattr(self._inner, "anthropic_client", None) if has_anthropic else None
        if has_anthropic:
            self._inner.anthropic_client = self._traced_clients.anthropic_client

        ctx = {"trace_id": scorer_trace_id, **self._eval_metadata} if scorer_trace_id else None
        token = _scorer_context.set(ctx)
        try:
            yield is_llm_scorer
        finally:
            _scorer_context.reset(token)
            if has_client:
                self._inner.client = original_client
            if has_anthropic:
                self._inner.anthropic_client = original_anthropic

    async def _run_eval_async(self, output, expected=None, **kwargs):
        case_name = _case_name_from_kwargs(kwargs)
        with self._invocation_context(case_name) as is_llm_scorer:
            result = await self._inner._run_eval_async(output, expected, **kwargs)
        if not is_llm_scorer and self._posthog_client:
            self._emit_scorer_span(case_name, result)
        return result

    def _run_eval_sync(self, output, expected=None, **kwargs):
        case_name = _case_name_from_kwargs(kwargs)
        with self._invocation_context(case_name) as is_llm_scorer:
            result = self._inner._run_eval_sync(output, expected, **kwargs)
        if not is_llm_scorer and self._posthog_client:
            self._emit_scorer_span(case_name, result)
        return result

    def _emit_scorer_span(self, case_name: str, result: Any) -> None:
        """Emit an ``$ai_span`` for a deterministic scorer on the agent trace."""
        agent_trace_id = self._agent_trace_id_lookup.get(case_name)
        if not agent_trace_id or not self._posthog_client:
            return

        score_value = getattr(result, "score", None)
        metadata = getattr(result, "metadata", {}) or {}

        self._posthog_client.capture(
            distinct_id=DISTINCT_ID,
            event="$ai_span",
            properties={
                "$ai_trace_id": agent_trace_id,
                "$ai_span_id": str(uuid.uuid4()),
                "$ai_parent_id": agent_trace_id,
                "$ai_span_name": f"scorer/{self._name()}",
                "$ai_output_state": {
                    "score": score_value,
                    **metadata,
                },
                "ai_product": "evals",
                "$ai_experiment_id": self._eval_metadata.get("experiment_id", ""),
                "$ai_experiment_name": self._eval_metadata.get("experiment_name", ""),
            },
        )


def wrap_scorers(
    scorers: Sequence[Any],
    posthog_client: Posthog,
    experiment_id: str,
    experiment_name: str,
    agent_trace_id_lookup: dict[str, str],
) -> tuple[list[Any], dict[tuple[str, str], str]]:
    """Wrap scorers with tracing.

    Returns (wrapped_scorers, scorer_traces dict).

    ``agent_trace_id_lookup`` maps case_name → agent trace_id. It's populated
    by the ``task()`` function and read by deterministic scorers to attach
    their spans to the agent trace.
    """
    traced_clients = create_traced_scorer_clients(posthog_client)
    scorer_traces: dict[tuple[str, str], str] = {}
    eval_metadata = {
        "experiment_id": experiment_id,
        "experiment_name": f"sandboxed-agent/{experiment_name}",
    }
    wrapped = [
        TracedScorer(
            s,
            traced_clients,
            eval_metadata,
            scorer_traces,
            posthog_client=posthog_client,
            agent_trace_id_lookup=agent_trace_id_lookup,
        )
        for s in scorers
    ]
    return wrapped, scorer_traces


def _case_name_from_kwargs(kwargs: dict) -> str:
    input_data = kwargs.get("input", {})
    return input_data.get("name", "unknown") if isinstance(input_data, dict) else "unknown"


def _parse_iso_timestamp(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class TraceEventEmitter:
    """Emits PostHog $ai_* events for a single eval case trace.

    Holds the PostHog client, trace_id, and experiment metadata so individual
    emit methods don't have to thread them through every call.
    """

    def __init__(
        self,
        client: Posthog,
        trace_id: str,
        experiment_id: str,
        experiment_name: str,
        case_name: str,
    ):
        self._client = client
        self._trace_id = trace_id
        self._experiment_id = experiment_id
        self._formatted_experiment_name = f"sandboxed-agent/{experiment_name}"
        self._case_name = case_name

    @property
    def _eval_metadata(self) -> dict[str, Any]:
        return {
            "ai_product": "evals",
            "$ai_experiment_id": self._experiment_id,
            "$ai_experiment_name": self._formatted_experiment_name,
        }

    def emit_parsed_events(self, parsed: ParsedLog) -> None:
        """Emit ``$ai_generation`` per model turn and ``$ai_span`` per log span."""
        error_spans = [s for s in parsed.spans if s.span_name == "error"]

        for gen in parsed.generations:
            self._emit_generation(gen, error_spans)
        for span in parsed.spans:
            self._emit_span(span)

        # NOTE: $ai_trace root event is emitted separately by emit_trace_root()
        # after scoring completes, so it can include scores in the output.

        logger.info(
            "Emitted child events for '%s' (trace=%s): %d generations, %d spans",
            self._case_name,
            self._trace_id,
            len(parsed.generations),
            len(parsed.spans),
        )

    def _emit_generation(self, gen: GenerationDescriptor, error_spans: list[SpanDescriptor]) -> None:
        # Prefer the real "model call invoked" time; fall back to first-output time.
        gen_start = _parse_iso_timestamp(gen.start_ts) or _parse_iso_timestamp(gen.timestamp)
        gen_end = _parse_iso_timestamp(gen.end_ts) or _parse_iso_timestamp(gen.timestamp)

        properties: dict[str, Any] = {
            "$ai_trace_id": self._trace_id,
            "$ai_span_id": str(uuid.uuid4()),
            "$ai_parent_id": self._trace_id,
            "$ai_model": DEFAULT_MODEL,
            "$ai_provider": DEFAULT_PROVIDER,
            "$ai_input": gen.input_messages,
            **self._eval_metadata,
        }
        if gen.output_content:
            properties["$ai_output_choices"] = [
                {"role": "assistant", "content": gen.output_content},
            ]

        # Token usage. The ACP agent-server emits one ``usage`` block per session
        # (at end_turn), so only the final generation carries non-empty counts when
        # a session spans multiple model calls.
        self._apply_token_usage(properties, gen.token_usage)

        if gen_start and gen_end and gen_end >= gen_start:
            properties["$ai_latency"] = (gen_end - gen_start).total_seconds()

        self._apply_matching_errors(properties, error_spans, gen_start, gen_end)

        capture_kwargs: dict[str, Any] = {}
        if gen_start:
            capture_kwargs["timestamp"] = gen_start

        self._client.capture(
            distinct_id=DISTINCT_ID,
            event="$ai_generation",
            properties=properties,
            **capture_kwargs,
        )

    @staticmethod
    def _apply_token_usage(properties: dict[str, Any], token_usage: dict[str, int]) -> None:
        if not token_usage:
            return
        if "inputTokens" in token_usage:
            properties["$ai_input_tokens"] = token_usage["inputTokens"]
        if "outputTokens" in token_usage:
            properties["$ai_output_tokens"] = token_usage["outputTokens"]
        if token_usage.get("cachedReadTokens"):
            properties["$ai_cache_read_input_tokens"] = token_usage["cachedReadTokens"]
        if token_usage.get("cachedWriteTokens"):
            properties["$ai_cache_creation_input_tokens"] = token_usage["cachedWriteTokens"]

    @staticmethod
    def _apply_matching_errors(
        properties: dict[str, Any],
        error_spans: list[SpanDescriptor],
        gen_start: datetime | None,
        gen_end: datetime | None,
    ) -> None:
        """Attribute errors that fired within this generation's time window."""
        if not gen_start:
            return
        matching: list[str] = []
        for span in error_spans:
            span_ts = _parse_iso_timestamp(span.timestamp)
            if not span_ts:
                continue
            if span_ts >= gen_start and (gen_end is None or span_ts <= gen_end):
                matching.append(span.content or "unknown error")
        if matching:
            properties["$ai_is_error"] = True
            properties["$ai_error"] = "; ".join(matching)[:2000]

    def _emit_span(self, span: SpanDescriptor) -> None:
        capture_kwargs: dict[str, Any] = {}
        span_ts = _parse_iso_timestamp(span.timestamp)
        if span_ts:
            capture_kwargs["timestamp"] = span_ts

        self._client.capture(
            distinct_id=DISTINCT_ID,
            event="$ai_span",
            properties={
                "$ai_trace_id": self._trace_id,
                "$ai_span_id": span.span_id,
                "$ai_parent_id": self._trace_id,
                "$ai_span_name": span.span_name,
                "$ai_output_state": span.content,
                **self._eval_metadata,
            },
            **capture_kwargs,
        )

    def emit_root(
        self,
        prompt: str,
        duration: float,
        first_timestamp: str,
        last_message: str = "",
        artifacts_summary: dict[str, Any] | None = None,
        scores: dict[str, float | None] | None = None,
        token_usage: dict[str, int] | None = None,
    ) -> None:
        """Emit the ``$ai_trace`` root event after scoring so output includes scores.

        Token usage is placed here (not on individual generations) because the ACP
        log only reports aggregate totals at ``end_turn``, not per sub-generation.
        """
        prompt_preview = prompt[:20].replace("\n", " ") if prompt else ""
        trace_name = f"{self._case_name}: {prompt_preview}" if prompt_preview else self._case_name

        output_state: dict[str, Any] = {}
        if last_message:
            output_state["last_message"] = last_message
        if scores:
            output_state["scores"] = scores
        if artifacts_summary:
            output_state["artifacts"] = artifacts_summary

        properties: dict[str, Any] = {
            "$ai_trace_id": self._trace_id,
            "$ai_trace_name": trace_name,
            "$ai_latency": duration,
            **self._eval_metadata,
        }
        if prompt:
            properties["$ai_input_state"] = {"prompt": prompt}
        if output_state:
            properties["$ai_output_state"] = output_state
        if token_usage:
            properties["$ai_input_tokens"] = token_usage.get("inputTokens", 0)
            properties["$ai_output_tokens"] = token_usage.get("outputTokens", 0)
            properties["$ai_cache_read_input_tokens"] = token_usage.get("cachedReadTokens", 0)

        capture_kwargs: dict[str, Any] = {}
        ts = _parse_iso_timestamp(first_timestamp)
        if ts:
            capture_kwargs["timestamp"] = ts

        self._client.capture(
            distinct_id=DISTINCT_ID,
            event="$ai_trace",
            properties=properties,
            **capture_kwargs,
        )


def emit_trace_events(
    client: Posthog,
    trace_id: str,
    experiment_id: str,
    experiment_name: str,
    case_name: str,
    parsed: ParsedLog,
) -> None:
    """Emit one ``$ai_generation`` per turn, plus ``$ai_span`` events.

    Thin wrapper over ``TraceEventEmitter.emit_parsed_events``.
    """
    TraceEventEmitter(client, trace_id, experiment_id, experiment_name, case_name).emit_parsed_events(parsed)


def emit_trace_root(
    client: Posthog,
    trace_id: str,
    experiment_id: str,
    experiment_name: str,
    case_name: str,
    prompt: str,
    duration: float,
    first_timestamp: str,
    last_message: str = "",
    artifacts_summary: dict[str, Any] | None = None,
    scores: dict[str, float | None] | None = None,
    token_usage: dict[str, int] | None = None,
) -> None:
    """Thin wrapper over ``TraceEventEmitter.emit_root``."""
    TraceEventEmitter(client, trace_id, experiment_id, experiment_name, case_name).emit_root(
        prompt=prompt,
        duration=duration,
        first_timestamp=first_timestamp,
        last_message=last_message,
        artifacts_summary=artifacts_summary,
        scores=scores,
        token_usage=token_usage,
    )


def emit_evaluation_events(
    client: Posthog,
    experiment_id: str,
    experiment_name: str,
    eval_results: list,
    scorer_traces: dict[tuple[str, str], str] | None = None,
) -> None:
    """Emit ``$ai_evaluation`` events for each scorer result in each eval case.

    ``scorer_traces`` maps ``(case_name, scorer_name)`` to the trace_id of
    the scorer's LLM call. If available, ``$ai_trace_id`` on the event
    points to the scorer trace (for inspecting the scorer's reasoning).
    """
    formatted_name = f"sandboxed-agent/{experiment_name}"

    for result in eval_results:
        case_name = result.input.get("name", "unknown") if isinstance(result.input, dict) else "unknown"
        metadata = result.metadata or {}
        agent_trace_id = metadata.get("trace_id")
        item_id = str(uuid.uuid4())

        # $ai_output = last assistant message
        last_message = ""
        if isinstance(result.output, dict):
            last_message = result.output.get("last_message", "")

        for scorer_name, score_value in (result.scores or {}).items():
            # Prefer scorer trace_id (links to scorer's LLM reasoning);
            # fall back to agent trace_id
            scorer_trace_id = scorer_traces.get((case_name, scorer_name)) if scorer_traces else None
            trace_id = scorer_trace_id or agent_trace_id

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
                    properties["$ai_input"] = prompt
            if last_message:
                properties["$ai_output"] = last_message
            if result.expected is not None:
                properties["$ai_expected"] = result.expected

            client.capture(distinct_id=DISTINCT_ID, event="$ai_evaluation", properties=properties)

    logger.info(
        "Emitted evaluation events for experiment '%s' (%d results)",
        experiment_name,
        len(eval_results),
    )
