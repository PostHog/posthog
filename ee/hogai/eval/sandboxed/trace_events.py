"""Emit sandboxed eval trace events ($ai_generation, $ai_span, $ai_trace,
$ai_evaluation) to a PostHog client.

Consumes a ``ParsedLog`` produced by ``acp_log.parse_log`` plus scoring
results from Braintrust. Owns the constants shared with scorer tracing
(``DISTINCT_ID``) so they live alongside their primary consumer.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Any

from posthoganalytics import Posthog

from .acp_log import GenerationDescriptor, ParsedLog, SpanDescriptor

logger = logging.getLogger(__name__)

DISTINCT_ID = "llma_eval"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_PROVIDER = "anthropic"


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
