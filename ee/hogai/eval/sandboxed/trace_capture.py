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


# ---------------------------------------------------------------------------
# Parsed log structures
# ---------------------------------------------------------------------------


@dataclass
class GenerationDescriptor:
    """One model turn: full conversation history → assistant response."""

    input_messages: list[dict[str, Any]] = field(default_factory=list)
    output_content: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    timestamp: str = ""


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


# ---------------------------------------------------------------------------
# ACP JSONL → per-turn generations + spans
# ---------------------------------------------------------------------------


def parse_log(raw_log: str, initial_prompt: str = "") -> ParsedLog:
    """Parse an ACP JSONL log into per-turn generations and span descriptors.

    Each generation represents one model API call with the **full accumulated
    conversation history** as input (matching how autoregressive LLMs work):
    - ``input_messages``: full message history sent to the model for this call
    - ``output_content``: the assistant's response (text + tool_use blocks)
    - ``token_usage``: populated on the final generation from ``end_turn``
    - ``timestamp``: ISO timestamp of the first agent output in this generation

    Generation boundaries are detected when a new ``agent_message`` arrives
    after tool results have been collected — this signals the model received
    the tool results and is producing a new response.

    ``initial_prompt`` is injected as the first user message because the
    agent-server's ``sendInitialTaskMessage`` doesn't emit a ``user_message``
    session update in the ACP log.
    """
    result = ParsedLog()

    # Full conversation history — grows with each generation.
    # Seed with the initial prompt (not present in the ACP log).
    history: list[dict[str, Any]] = []
    if initial_prompt:
        history.append({"role": "user", "content": initial_prompt})

    # State for the current generation being built
    current_output: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []
    last_token_usage: dict[str, int] = {}
    gen_timestamp: str = ""

    def _flush_generation(token_usage: dict[str, int] | None = None) -> None:
        """Flush accumulated output into a GenerationDescriptor with full history as input."""
        nonlocal current_output, gen_timestamp
        if not current_output:
            return
        result.generations.append(
            GenerationDescriptor(
                input_messages=list(history),
                output_content=list(current_output),
                token_usage=token_usage or {},
                timestamp=gen_timestamp,
            )
        )
        # Add the assistant response to history for the next generation
        history.append({"role": "assistant", "content": list(current_output)})
        current_output = []
        gen_timestamp = ""

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
                last_token_usage = {
                    "inputTokens": usage.get("inputTokens", 0),
                    "outputTokens": usage.get("outputTokens", 0),
                    "cachedReadTokens": usage.get("cachedReadTokens", 0),
                    "totalTokens": usage.get("totalTokens", 0),
                }
            if entry_result.get("stopReason") == "end_turn":
                _flush_generation(token_usage=last_token_usage)
                last_token_usage = {}
                continue

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
                        content=msg,
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
                    content=msg or "unknown error",
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
            _flush_generation()
            # Flush any pending tool results into history
            if pending_tool_results:
                history.append({"role": "user", "content": list(pending_tool_results)})
                pending_tool_results = []

            text = _extract_text(update)
            if text:
                history.append({"role": "user", "content": text})

        # --- Agent message (text block) ---
        elif session_update == "agent_message":
            # If tool results are pending, this means the model has received them
            # and is producing a new response — flush the previous generation.
            if pending_tool_results:
                _flush_generation()
                history.append({"role": "user", "content": list(pending_tool_results)})
                pending_tool_results = []

            if not gen_timestamp:
                gen_timestamp = ts
            text = _extract_text(update)
            if text:
                current_output.append({"type": "text", "text": text})

        # --- Tool call start ---
        elif session_update == "tool_call":
            if not gen_timestamp:
                gen_timestamp = ts
            meta = update.get("_meta", {})
            cc = meta.get("claudeCode", {}) if isinstance(meta, dict) else {}
            tool_name = cc.get("toolName", update.get("title", "unknown_tool"))
            tool_call_id = update.get("toolCallId", str(uuid.uuid4()))
            raw_input = update.get("rawInput", {})

            current_output.append(
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
                raw_output = update.get("rawOutput", "")
                content = _extract_text(update)
                output_text = raw_output if raw_output else (content or "")
                if isinstance(output_text, dict):
                    output_text = json.dumps(output_text)

                is_error = status in ("failed", "error")
                tool_result: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": str(output_text) if output_text else "(no output)",
                }
                if is_error:
                    tool_result["is_error"] = True
                pending_tool_results.append(tool_result)

        # Skip agent_message_chunk, agent_thought_chunk, usage_update, available_commands_update

    # Flush anything remaining (e.g. if end_turn was missing)
    if pending_tool_results:
        history.append({"role": "user", "content": list(pending_tool_results)})
    _flush_generation()

    return result


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
# Traced scorer wrapper
# ---------------------------------------------------------------------------


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

    async def _run_eval_async(self, output, expected=None, **kwargs):
        case_name = _case_name_from_kwargs(kwargs)
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
            result = await self._inner._run_eval_async(output, expected, **kwargs)
        finally:
            _scorer_context.reset(token)
            if has_client:
                self._inner.client = original_client
            if has_anthropic:
                self._inner.anthropic_client = original_anthropic

        # Emit deterministic scorers as spans on the agent trace
        if not is_llm_scorer and self._posthog_client:
            self._emit_scorer_span(case_name, result)

        return result

    def _run_eval_sync(self, output, expected=None, **kwargs):
        case_name = _case_name_from_kwargs(kwargs)
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
            result = self._inner._run_eval_sync(output, expected, **kwargs)
        finally:
            _scorer_context.reset(token)
            if has_client:
                self._inner.client = original_client
            if has_anthropic:
                self._inner.anthropic_client = original_anthropic

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


# ---------------------------------------------------------------------------
# Emit trace events to PostHog
# ---------------------------------------------------------------------------


def _parse_iso_timestamp(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def emit_trace_events(
    client: Posthog,
    trace_id: str,
    experiment_id: str,
    experiment_name: str,
    case_name: str,
    prompt: str,
    parsed: ParsedLog,
    duration: float,
    artifacts_summary: dict[str, Any] | None = None,
) -> None:
    """Emit one ``$ai_generation`` per turn, plus ``$ai_span`` and ``$ai_trace`` events.

    Uses timestamps from the ACP log so events sort chronologically in the trace view.
    """
    formatted_exp_name = f"sandboxed-agent/{experiment_name}"

    # Common properties for linking traces to the eval experiment
    eval_metadata: dict[str, Any] = {
        "ai_product": "evals",
        "$ai_experiment_id": experiment_id,
        "$ai_experiment_name": formatted_exp_name,
    }

    # $ai_generation — one per model turn, with accumulated history as input
    for gen in parsed.generations:
        generation_id = str(uuid.uuid4())
        gen_properties: dict[str, Any] = {
            "$ai_trace_id": trace_id,
            "$ai_span_id": generation_id,
            "$ai_parent_id": trace_id,
            "$ai_model": DEFAULT_MODEL,
            "$ai_provider": DEFAULT_PROVIDER,
            "$ai_input": gen.input_messages,
            **eval_metadata,
        }
        if gen.output_content:
            gen_properties["$ai_output_choices"] = gen.output_content

        capture_kwargs: dict[str, Any] = {}
        gen_ts = _parse_iso_timestamp(gen.timestamp)
        if gen_ts:
            capture_kwargs["timestamp"] = gen_ts

        client.capture(distinct_id=DISTINCT_ID, event="$ai_generation", properties=gen_properties, **capture_kwargs)

    # $ai_span — non-AI events (console, errors)
    for span in parsed.spans:
        capture_kwargs = {}
        span_ts = _parse_iso_timestamp(span.timestamp)
        if span_ts:
            capture_kwargs["timestamp"] = span_ts

        client.capture(
            distinct_id=DISTINCT_ID,
            event="$ai_span",
            properties={
                "$ai_trace_id": trace_id,
                "$ai_span_id": span.span_id,
                "$ai_parent_id": trace_id,
                "$ai_span_name": span.span_name,
                "$ai_output_state": span.content,
                **eval_metadata,
            },
            **capture_kwargs,
        )

    # NOTE: $ai_trace root event is emitted separately by emit_trace_root()
    # after scoring completes, so it can include scores in the output.

    logger.info(
        "Emitted child events for '%s' (trace=%s): %d generations, %d spans",
        case_name,
        trace_id,
        len(parsed.generations),
        len(parsed.spans),
    )


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
    """Emit the ``$ai_trace`` root event after scoring so output includes scores.

    Token usage is placed here (not on individual generations) because the ACP
    log only reports aggregate totals at ``end_turn``, not per sub-generation.
    """
    formatted_exp_name = f"sandboxed-agent/{experiment_name}"
    prompt_preview = prompt[:20].replace("\n", " ") if prompt else ""
    trace_name = f"{case_name}: {prompt_preview}" if prompt_preview else case_name

    output_state: dict[str, Any] = {}
    if last_message:
        output_state["last_message"] = last_message
    if scores:
        output_state["scores"] = scores
    if artifacts_summary:
        output_state["artifacts"] = artifacts_summary

    trace_properties: dict[str, Any] = {
        "$ai_trace_id": trace_id,
        "$ai_trace_name": trace_name,
        "$ai_latency": duration,
        "ai_product": "evals",
        "$ai_experiment_id": experiment_id,
        "$ai_experiment_name": formatted_exp_name,
    }
    if prompt:
        trace_properties["$ai_input_state"] = {"prompt": prompt}
    if output_state:
        trace_properties["$ai_output_state"] = output_state
    if token_usage:
        trace_properties["$ai_input_tokens"] = token_usage.get("inputTokens", 0)
        trace_properties["$ai_output_tokens"] = token_usage.get("outputTokens", 0)
        trace_properties["$ai_cache_read_input_tokens"] = token_usage.get("cachedReadTokens", 0)

    capture_kwargs: dict[str, Any] = {}
    ts = _parse_iso_timestamp(first_timestamp)
    if ts:
        capture_kwargs["timestamp"] = ts

    client.capture(distinct_id=DISTINCT_ID, event="$ai_trace", properties=trace_properties, **capture_kwargs)


# ---------------------------------------------------------------------------
# Emit evaluation events to PostHog
# ---------------------------------------------------------------------------


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
