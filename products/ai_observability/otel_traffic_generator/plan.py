"""Deterministic plan model and scenario catalog for the OTel AI traffic generator.

A *plan* is a pure, reviewable description of the synthetic AI traffic to send:
a list of traces, each a list of OTLP spans with their gen_ai/Vercel/Traceloop/
Pydantic attributes, plus the expectations we assert after ingestion. Plans carry
no wall-clock time and no concrete span IDs — those are resolved at run time from
``(plan_id, run_id)`` — so ``plan(seed=X)`` is byte-stable and a single plan can be
run many times and compared across runs.
"""

from __future__ import annotations

import json
import hashlib
from typing import Any, Literal, TypedDict

# ----- attribute value encoding (maps onto OTLP AnyValue) -------------------

AttrType = Literal["str", "int", "double", "bool", "json"]


class AttrVal(TypedDict):
    t: AttrType
    v: Any


def s(v: str) -> AttrVal:
    return {"t": "str", "v": v}


def i(v: int) -> AttrVal:
    return {"t": "int", "v": v}


def d(v: float) -> AttrVal:
    return {"t": "double", "v": v}


def b(v: bool) -> AttrVal:
    return {"t": "bool", "v": v}


def j(v: Any) -> AttrVal:
    """A structured value serialized to a JSON string (how gen_ai.*.messages arrive)."""
    return {"t": "json", "v": v}


# ----- plan structures ------------------------------------------------------

# Second granularity so the whole scenario catalog fits well under any single
# request's span budget while keeping realistic sub-second latencies.
SECOND_NS = 1_000_000_000


class SpanSpec(TypedDict):
    index: int
    name: str
    # What this span is expected to become after capture + ingestion.
    expect_event: str
    parent_index: int | None
    start_offset_ns: int
    end_offset_ns: int
    attributes: dict[str, AttrVal]
    # Optional error status -> $ai_is_error / $ai_error / $ai_http_status.
    error: ErrorSpec | None


class ErrorSpec(TypedDict):
    message: str
    exception_type: str
    exception_message: str
    http_status: int


class GenerationExpect(TypedDict, total=False):
    span_index: int
    model: str
    input_tokens: int
    output_tokens: int
    provider: str
    cost_positive: bool
    latency_positive: bool
    input_present: bool
    output_present: bool
    cache_read_tokens: int
    is_error: bool


class TraceSpec(TypedDict):
    index: int
    scenario: str
    distinct_id: str
    spans: list[SpanSpec]
    # Expected count of each ingested event type for this trace.
    expect_events: dict[str, int]
    # Per-generation/embedding property expectations, verified by span_index.
    expect_props: list[GenerationExpect]


class Plan(TypedDict):
    version: int
    plan_id: str
    seed: int
    scenarios: list[str]
    multiplier: int
    traces: list[TraceSpec]
    expect_totals: dict[str, int]


PLAN_VERSION = 1


# ----- message helpers ------------------------------------------------------


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"type": "text", "content": text}]}


def _system(text: str) -> dict[str, Any]:
    return {"role": "system", "parts": [{"type": "text", "content": text}]}


def _assistant(text: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {"role": "assistant", "parts": [{"type": "text", "content": text}], "finish_reason": finish_reason}


def _assistant_tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "parts": [{"type": "tool_call", "id": call_id, "name": name, "arguments": arguments}],
        "finish_reason": "tool_calls",
    }


# ----- span builders --------------------------------------------------------


def _sdk_attrs(name: str = "opentelemetry", version: str = "1.29.0") -> dict[str, AttrVal]:
    return {"telemetry.sdk.name": s(name), "telemetry.sdk.version": s(version)}


def _root_span(scenario_title: str, model: str, provider: str, end_s: float) -> SpanSpec:
    """A parentless AI span: capture -> $ai_span, ingestion promotes it to $ai_trace."""
    return {
        "index": 0,
        "name": scenario_title,
        "expect_event": "$ai_trace",
        "parent_index": None,
        "start_offset_ns": 0,
        "end_offset_ns": int(end_s * SECOND_NS),
        # gen_ai.* prefix (so capture accepts the span) but no operation.name (so it
        # classifies as $ai_span, not $ai_generation). request.model/system fall
        # back to $ai_model/$ai_provider on the trace.
        "attributes": {"gen_ai.request.model": s(model), "gen_ai.system": s(provider)},
        "error": None,
    }


def _generation_span(
    index: int,
    name: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    prompt: str,
    completion: str,
    start_s: float,
    end_s: float,
    *,
    parent_index: int | None = 0,
    response_model: str | None = None,
    system_prompt: str | None = None,
    extra: dict[str, AttrVal] | None = None,
) -> SpanSpec:
    messages: list[dict[str, Any]] = []
    if system_prompt is not None:
        messages.append(_system(system_prompt))
    messages.append(_user(prompt))
    attributes: dict[str, AttrVal] = {
        "gen_ai.operation.name": s("chat"),
        "gen_ai.request.model": s(model),
        "gen_ai.response.model": s(response_model or model),
        "gen_ai.provider.name": s(provider),
        "gen_ai.usage.input_tokens": i(input_tokens),
        "gen_ai.usage.output_tokens": i(output_tokens),
        "gen_ai.input.messages": j(messages),
        "gen_ai.output.messages": j([_assistant(completion)]),
        "server.address": s(f"api.{provider}.com"),
        **_sdk_attrs(),
    }
    if extra:
        attributes.update(extra)
    return {
        "index": index,
        "name": name,
        "expect_event": "$ai_generation",
        "parent_index": parent_index,
        "start_offset_ns": int(start_s * SECOND_NS),
        "end_offset_ns": int(end_s * SECOND_NS),
        "attributes": attributes,
        "error": None,
    }


def _embedding_span(
    index: int,
    name: str,
    model: str,
    provider: str,
    input_tokens: int,
    text: str,
    start_s: float,
    end_s: float,
    *,
    parent_index: int | None = 0,
) -> SpanSpec:
    return {
        "index": index,
        "name": name,
        "expect_event": "$ai_embedding",
        "parent_index": parent_index,
        "start_offset_ns": int(start_s * SECOND_NS),
        "end_offset_ns": int(end_s * SECOND_NS),
        "attributes": {
            "gen_ai.operation.name": s("embeddings"),
            "gen_ai.request.model": s(model),
            "gen_ai.response.model": s(model),
            "gen_ai.provider.name": s(provider),
            "gen_ai.usage.input_tokens": i(input_tokens),
            "gen_ai.input.messages": j([_user(text)]),
            **_sdk_attrs(),
        },
        "error": None,
    }


# ----- scenario catalog -----------------------------------------------------
#
# Each scenario returns the spans + expectations for one trace. distinct_id and
# trace index are filled in by build_plan. Scenarios deliberately span the whole
# classification + mapping surface: gen_ai / Vercel / Traceloop / Pydantic
# namespaces, generation / embedding / span / trace event types, tool calls,
# cache tokens, and error status.

ScenarioFn = Any  # Callable[[int, str], TraceSpec], kept loose to avoid import churn.


def _openai_chat(index: int, distinct_id: str) -> TraceSpec:
    spans = [
        _root_span("OpenAI chat", "gpt-4o", "openai", 3.4),
        _generation_span(
            1,
            "chat gpt-4o",
            "gpt-4o",
            "openai",
            142,
            318,
            "Explain retrieval-augmented generation in two sentences.",
            "RAG augments a model's prompt with documents fetched from an external "
            "store at query time. This grounds answers in up-to-date, source-backed "
            "context the model wasn't trained on.",
            0.2,
            3.1,
            response_model="gpt-4o-2024-08-06",
            system_prompt="You are a concise technical assistant.",
        ),
    ]
    return {
        "index": index,
        "scenario": "openai_chat",
        "distinct_id": distinct_id,
        "spans": spans,
        "expect_events": {"$ai_trace": 1, "$ai_generation": 1},
        "expect_props": [
            {
                "span_index": 1,
                "model": "gpt-4o-2024-08-06",
                "input_tokens": 142,
                "output_tokens": 318,
                "provider": "openai",
                "cost_positive": True,
                "latency_positive": True,
                "input_present": True,
                "output_present": True,
            }
        ],
    }


def _multi_turn(index: int, distinct_id: str) -> TraceSpec:
    spans = [
        _root_span("Support conversation", "gpt-4o-mini", "openai", 6.0),
        _generation_span(
            1,
            "chat turn 1",
            "gpt-4o-mini",
            "openai",
            88,
            120,
            "My order hasn't arrived, can you check status 10432?",
            "Order 10432 shipped yesterday and is out for delivery today. Anything else?",
            0.2,
            2.0,
        ),
        _generation_span(
            2,
            "chat turn 2",
            "gpt-4o-mini",
            "openai",
            210,
            64,
            "Thanks. Can you also email me the receipt?",
            "Done — I've emailed the receipt to the address on file.",
            2.4,
            5.8,
        ),
    ]
    return {
        "index": index,
        "scenario": "multi_turn",
        "distinct_id": distinct_id,
        "spans": spans,
        "expect_events": {"$ai_trace": 1, "$ai_generation": 2},
        "expect_props": [
            {"span_index": 1, "model": "gpt-4o-mini", "cost_positive": True, "latency_positive": True},
            {"span_index": 2, "model": "gpt-4o-mini", "cost_positive": True, "latency_positive": True},
        ],
    }


def _rag_embedding(index: int, distinct_id: str) -> TraceSpec:
    spans = [
        _root_span("RAG pipeline", "gpt-4o", "openai", 4.5),
        _embedding_span(
            1,
            "embeddings text-embedding-3-small",
            "text-embedding-3-small",
            "openai",
            96,
            "What is the refund window for enterprise plans?",
            0.2,
            0.6,
        ),
        _generation_span(
            2,
            "chat gpt-4o",
            "gpt-4o",
            "openai",
            540,
            180,
            "Answer using the retrieved policy documents.",
            "Enterprise plans have a 30-day refund window from the invoice date.",
            0.8,
            4.2,
            response_model="gpt-4o-2024-08-06",
        ),
    ]
    return {
        "index": index,
        "scenario": "rag_embedding",
        "distinct_id": distinct_id,
        "spans": spans,
        "expect_events": {"$ai_trace": 1, "$ai_embedding": 1, "$ai_generation": 1},
        "expect_props": [
            {"span_index": 1, "model": "text-embedding-3-small", "cost_positive": True, "input_present": True},
            {"span_index": 2, "model": "gpt-4o-2024-08-06", "cost_positive": True, "latency_positive": True},
        ],
    }


def _tool_call(index: int, distinct_id: str) -> TraceSpec:
    gen = _generation_span(
        1,
        "chat gpt-4o tools",
        "gpt-4o",
        "openai",
        160,
        48,
        "What's the weather in Lisbon and should I bring an umbrella?",
        "",
        0.2,
        2.0,
        response_model="gpt-4o-2024-08-06",
    )
    # Override the output with a tool call so tool extraction has something to chew on.
    gen["attributes"]["gen_ai.output.messages"] = j(
        [_assistant_tool_call("call_wx1", "get_weather", {"city": "Lisbon"})]
    )
    tool_span: SpanSpec = {
        "index": 2,
        "name": "tool get_weather",
        "expect_event": "$ai_span",
        "parent_index": 1,
        "start_offset_ns": int(2.0 * SECOND_NS),
        "end_offset_ns": int(2.3 * SECOND_NS),
        # gen_ai.* prefix with no operation.name -> $ai_span (child, not promoted).
        "attributes": {"gen_ai.tool.name": s("get_weather"), "gen_ai.tool.type": s("function")},
        "error": None,
    }
    spans = [_root_span("Agent with tools", "gpt-4o", "openai", 3.0), gen, tool_span]
    return {
        "index": index,
        "scenario": "tool_call",
        "distinct_id": distinct_id,
        "spans": spans,
        "expect_events": {"$ai_trace": 1, "$ai_generation": 1, "$ai_span": 1},
        "expect_props": [{"span_index": 1, "model": "gpt-4o-2024-08-06", "cost_positive": True}],
    }


def _error_generation(index: int, distinct_id: str) -> TraceSpec:
    gen = _generation_span(
        1,
        "chat gpt-4o (error)",
        "gpt-4o",
        "openai",
        75,
        0,
        "Summarize this 900-page document.",
        "",
        0.2,
        1.1,
    )
    gen["expect_event"] = "$ai_generation"
    gen["error"] = {
        "message": "rate limited",
        "exception_type": "RateLimitError",
        "exception_message": "429 Too Many Requests",
        "http_status": 429,
    }
    spans = [_root_span("Failed generation", "gpt-4o", "openai", 1.3), gen]
    return {
        "index": index,
        "scenario": "error_generation",
        "distinct_id": distinct_id,
        "spans": spans,
        "expect_events": {"$ai_trace": 1, "$ai_generation": 1},
        "expect_props": [{"span_index": 1, "model": "gpt-4o", "is_error": True}],
    }


def _anthropic_cache(index: int, distinct_id: str) -> TraceSpec:
    gen = _generation_span(
        1,
        "chat claude cache",
        "claude-sonnet-4.5",
        "anthropic",
        1200,
        220,
        "Given the cached system prompt, draft a release note.",
        "Here is the release note draft based on the provided changelog.",
        0.2,
        3.6,
        system_prompt="You are a release-notes writer. [large cached context]",
        extra={
            "gen_ai.usage.cache_read.input_tokens": i(1000),
            "gen_ai.usage.cache_creation.input_tokens": i(200),
        },
    )
    spans = [_root_span("Anthropic cached prompt", "claude-sonnet-4.5", "anthropic", 3.8), gen]
    return {
        "index": index,
        "scenario": "anthropic_cache",
        "distinct_id": distinct_id,
        "spans": spans,
        "expect_events": {"$ai_trace": 1, "$ai_generation": 1},
        "expect_props": [
            {
                "span_index": 1,
                "model": "claude-sonnet-4.5",
                "provider": "anthropic",
                "cost_positive": True,
                "cache_read_tokens": 1000,
            }
        ],
    }


def _vercel_ai(index: int, distinct_id: str) -> TraceSpec:
    # Vercel AI SDK: ai.* namespace. The root ai.* span with no .doGenerate/.doStream
    # classifies as $ai_span (-> $ai_trace); the .doGenerate child is the generation.
    root: SpanSpec = {
        "index": 0,
        "name": "ai.generateText",
        "expect_event": "$ai_trace",
        "parent_index": None,
        "start_offset_ns": 0,
        "end_offset_ns": int(2.6 * SECOND_NS),
        "attributes": {"ai.operationId": s("ai.generateText"), "gen_ai.request.model": s("gpt-4o")},
        "error": None,
    }
    child: SpanSpec = {
        "index": 1,
        "name": "ai.generateText.doGenerate",
        "expect_event": "$ai_generation",
        "parent_index": 0,
        "start_offset_ns": int(0.1 * SECOND_NS),
        "end_offset_ns": int(2.5 * SECOND_NS),
        "attributes": {
            "ai.operationId": s("ai.generateText.doGenerate"),
            "gen_ai.request.model": s("gpt-4o"),
            "gen_ai.response.model": s("gpt-4o-2024-08-06"),
            "gen_ai.usage.input_tokens": i(130),
            "gen_ai.usage.output_tokens": i(90),
            "gen_ai.input.messages": j([_user("Write a haiku about latency.")]),
            "gen_ai.output.messages": j(
                [_assistant("Packets in the dark / waiting on a distant ACK / dawn of the reply")]
            ),
            **_sdk_attrs("vercel-ai", "4.0.0"),
        },
        "error": None,
    }
    return {
        "index": index,
        "scenario": "vercel_ai",
        "distinct_id": distinct_id,
        "spans": [root, child],
        "expect_events": {"$ai_trace": 1, "$ai_generation": 1},
        "expect_props": [
            {"span_index": 1, "model": "gpt-4o-2024-08-06", "cost_positive": True, "latency_positive": True}
        ],
    }


def _traceloop(index: int, distinct_id: str) -> TraceSpec:
    # Traceloop / OpenLLMetry: llm.request.type drives classification (reclassified
    # from $ai_span -> $ai_generation in ingestion).
    root: SpanSpec = {
        "index": 0,
        "name": "workflow.rag",
        "expect_event": "$ai_trace",
        "parent_index": None,
        "start_offset_ns": 0,
        "end_offset_ns": int(3.0 * SECOND_NS),
        "attributes": {"traceloop.workflow.name": s("rag"), "traceloop.span.kind": s("workflow")},
        "error": None,
    }
    child: SpanSpec = {
        "index": 1,
        "name": "openai.chat",
        "expect_event": "$ai_generation",
        "parent_index": 0,
        "start_offset_ns": int(0.1 * SECOND_NS),
        "end_offset_ns": int(2.8 * SECOND_NS),
        "attributes": {
            "llm.request.type": s("chat"),
            "gen_ai.request.model": s("gpt-4o-mini"),
            "gen_ai.response.model": s("gpt-4o-mini"),
            "gen_ai.system": s("openai"),
            "gen_ai.usage.prompt_tokens": i(210),
            "gen_ai.usage.completion_tokens": i(75),
            "gen_ai.input.messages": j([_user("Classify this ticket: 'app crashes on export'.")]),
            "gen_ai.output.messages": j([_assistant("Category: bug. Severity: high.")]),
            **_sdk_attrs("traceloop", "0.30.0"),
        },
        "error": None,
    }
    return {
        "index": index,
        "scenario": "traceloop",
        "distinct_id": distinct_id,
        "spans": [root, child],
        "expect_events": {"$ai_trace": 1, "$ai_generation": 1},
        "expect_props": [{"span_index": 1, "model": "gpt-4o-mini", "cost_positive": True, "latency_positive": True}],
    }


def _pydantic_ai(index: int, distinct_id: str) -> TraceSpec:
    # Pydantic AI: pydantic_ai.* -> $ai_span for every span (root promoted to trace).
    root: SpanSpec = {
        "index": 0,
        "name": "agent run",
        "expect_event": "$ai_trace",
        "parent_index": None,
        "start_offset_ns": 0,
        "end_offset_ns": int(2.2 * SECOND_NS),
        "attributes": {"pydantic_ai.agent_name": s("weather_agent")},
        "error": None,
    }
    child: SpanSpec = {
        "index": 1,
        "name": "model request",
        "expect_event": "$ai_span",
        "parent_index": 0,
        "start_offset_ns": int(0.1 * SECOND_NS),
        "end_offset_ns": int(2.0 * SECOND_NS),
        "attributes": {"pydantic_ai.step": s("model_request"), "gen_ai.request.model": s("gpt-4o")},
        "error": None,
    }
    return {
        "index": index,
        "scenario": "pydantic_ai",
        "distinct_id": distinct_id,
        "spans": [root, child],
        "expect_events": {"$ai_trace": 1, "$ai_span": 1},
        "expect_props": [],
    }


def _gemini_chat(index: int, distinct_id: str) -> TraceSpec:
    spans = [
        _root_span("Gemini chat", "gemini-2.5-pro", "google", 2.8),
        _generation_span(
            1,
            "chat gemini-2.5-pro",
            "gemini-2.5-pro",
            "google",
            98,
            210,
            "Give me three names for a hedgehog-themed coffee shop.",
            "Prickly Brew, The Spiny Bean, Hedgehog & Portafilter.",
            0.2,
            2.5,
        ),
    ]
    return {
        "index": index,
        "scenario": "gemini_chat",
        "distinct_id": distinct_id,
        "spans": spans,
        "expect_events": {"$ai_trace": 1, "$ai_generation": 1},
        "expect_props": [
            {
                "span_index": 1,
                "model": "gemini-2.5-pro",
                "provider": "google",
                "cost_positive": True,
                "latency_positive": True,
            }
        ],
    }


SCENARIOS: dict[str, ScenarioFn] = {
    "openai_chat": _openai_chat,
    "multi_turn": _multi_turn,
    "rag_embedding": _rag_embedding,
    "tool_call": _tool_call,
    "error_generation": _error_generation,
    "anthropic_cache": _anthropic_cache,
    "vercel_ai": _vercel_ai,
    "traceloop": _traceloop,
    "pydantic_ai": _pydantic_ai,
    "gemini_chat": _gemini_chat,
}

DEFAULT_SCENARIOS: list[str] = list(SCENARIOS.keys())


# ----- plan construction ----------------------------------------------------


def build_plan(seed: int, scenarios: list[str], multiplier: int) -> Plan:
    """Build a deterministic plan. Same (seed, scenarios, multiplier) -> identical bytes."""
    if multiplier < 1:
        raise ValueError("multiplier must be >= 1")
    unknown = [name for name in scenarios if name not in SCENARIOS]
    if unknown:
        raise ValueError(f"unknown scenarios: {unknown}. known: {sorted(SCENARIOS)}")

    traces: list[TraceSpec] = []
    trace_index = 0
    for copy in range(multiplier):
        for name in scenarios:
            # distinct_id namespaced by seed + copy so multiplier copies are
            # distinct users but fully deterministic.
            distinct_id = f"otelgen-s{seed}-u{copy}-{name}"
            traces.append(SCENARIOS[name](trace_index, distinct_id))
            trace_index += 1

    expect_totals: dict[str, int] = {}
    for trace in traces:
        for event, count in trace["expect_events"].items():
            expect_totals[event] = expect_totals.get(event, 0) + count

    plan: Plan = {
        "version": PLAN_VERSION,
        "plan_id": "",
        "seed": seed,
        "scenarios": scenarios,
        "multiplier": multiplier,
        "traces": traces,
        "expect_totals": expect_totals,
    }
    plan["plan_id"] = _plan_id(plan)
    return plan


def _canonical(plan: Plan) -> str:
    """Stable serialization used for both plan_id hashing and on-disk storage."""
    without_id = {k: v for k, v in plan.items() if k != "plan_id"}
    return json.dumps(without_id, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _plan_id(plan: Plan) -> str:
    return hashlib.sha256(_canonical(plan).encode("utf-8")).hexdigest()[:16]


def dumps(plan: Plan) -> str:
    return json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True)


def load(path: str) -> Plan:
    with open(path, encoding="utf-8") as f:
        plan = json.load(f)
    expected = _plan_id(plan)
    if plan.get("plan_id") != expected:
        raise ValueError(
            f"plan_id mismatch in {path}: file has {plan.get('plan_id')!r}, "
            f"content hashes to {expected!r}. The plan was edited by hand — regenerate it."
        )
    return plan
