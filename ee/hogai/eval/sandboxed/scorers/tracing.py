"""Wrap Braintrust scorers so their LLM calls go through PostHog-traced clients.

For LLM-based scorers (``autoevals.LLMClassifier`` subclasses that expose a
``client`` attribute), the wrapper swaps the inner scorer's client for a
PostHog-traced OpenAI/Anthropic client for the duration of each invocation.
For deterministic scorers, the wrapper just records a scorer trace_id and
emits a summary ``$ai_span`` on the agent trace after scoring completes.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from braintrust_core.score import Scorer
from posthoganalytics import Posthog

from ..trace_events import DISTINCT_ID

# Context var for injecting per-scorer-invocation trace properties
# into the traced OpenAI client's ``create()`` calls.
_scorer_context: ContextVar[dict[str, Any] | None] = ContextVar("_scorer_context", default=None)


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

    # Traced OpenAI client (for autoevals LLMClassifier scorers)
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

    # Traced Anthropic client
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
            self._inner.client = self._traced_clients.openai_llm_client  # ty: ignore[invalid-assignment]

        original_anthropic = getattr(self._inner, "anthropic_client", None) if has_anthropic else None
        if has_anthropic:
            self._inner.anthropic_client = self._traced_clients.anthropic_client  # ty: ignore[invalid-assignment]

        ctx = {"trace_id": scorer_trace_id, **self._eval_metadata} if scorer_trace_id else None
        token = _scorer_context.set(ctx)
        try:
            yield is_llm_scorer
        finally:
            _scorer_context.reset(token)
            if has_client:
                self._inner.client = original_client  # ty: ignore[invalid-assignment]
            if has_anthropic:
                self._inner.anthropic_client = original_anthropic  # ty: ignore[invalid-assignment]

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
