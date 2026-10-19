from datetime import timedelta

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.event import TraceEvent
from products.ai_observability.backend.logic.traces.tree import build_tree
from products.ai_observability.backend.logic.traces.usage import Usage

from .rows import T0, make_row


def event(**overrides: object) -> TraceEvent:
    return TraceEvent(row=make_row(**overrides), trace_id="trace-1")


@parameterized.expand(
    [
        ("generation id wins", {"generation_id": "g", "span_id": "s", "uuid": "u"}, "g"),
        ("span id next", {"span_id": "s", "uuid": "u"}, "s"),
        ("uuid last", {"uuid": "u"}, "u"),
    ]
)
def test_node_key(_name: str, overrides: dict[str, object], expected: str) -> None:
    assert event(**overrides).node_key == expected


def test_parent_key_falls_back_to_the_trace() -> None:
    assert event(parent_id=None).parent_key == "trace-1"


@parameterized.expand(
    [
        ("flag", {"is_error": True}, True),
        ("truthy error property without flag", {"error_is_truthy": True}, True),
        ("clean", {}, False),
    ]
)
def test_has_error(_name: str, overrides: dict[str, object], expected: bool) -> None:
    assert event(**overrides).has_error is expected


@parameterized.expand(
    [
        ("span name wins", {"event": "$ai_generation", "span_name": "plan", "model": "gpt"}, "plan"),
        ("model and provider", {"event": "$ai_generation", "model": "gpt", "provider": "openai"}, "gpt (openai)"),
        ("generation fallback", {"event": "$ai_generation"}, "Generation"),
        ("embedding fallback", {"event": "$ai_embedding", "provider": "openai"}, "Embedding (openai)"),
        ("span fallback", {"event": "$ai_span"}, "Span"),
    ]
)
def test_title(_name: str, overrides: dict[str, object], expected: str) -> None:
    assert event(**overrides).title == expected


@parameterized.expand(
    [
        ("sdk events are captured when they end", None, T0 - timedelta(seconds=2)),
        ("otel spans keep their start", "otel", T0),
    ]
)
def test_started_at(_name: str, source: str | None, expected: object) -> None:
    assert event(timestamp=T0, latency=2.0, ingestion_source=source).started_at == expected


def test_a_huge_latency_keeps_the_raw_timestamp_and_still_builds_a_tree() -> None:
    huge = event(timestamp=T0, latency=1e14)

    assert huge.started_at == T0
    assert len(build_tree([huge], "trace-1")) == 1


def test_rolled_up_keeps_own_values_and_leaves_unknown_cost_unknown() -> None:
    parts = [Usage(latency_s=1.0, input_tokens=2), Usage(cost_usd=None, latency_s=None, input_tokens=None)]

    rolled = Usage(latency_s=5.0).rolled_up(parts)

    assert rolled == Usage(cost_usd=None, latency_s=5.0, input_tokens=2, output_tokens=0)


def test_latency_ms_treats_zero_and_overflow_as_unknown() -> None:
    assert Usage(latency_s=0.0).latency_ms is None
    assert Usage(latency_s=1e306).latency_ms is None
    assert Usage(latency_s=1.5).latency_ms == 1500.0
