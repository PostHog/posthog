"""Tests for the generator's core contract: determinism and correct OTLP shape.

No network. These guard the promises the tool is built on — that a plan is
byte-stable for a seed, that a run is reproducible for a fixed (run_id,
base_time) yet independently scoped otherwise, and that the emitted OTLP spans
carry the attributes ingestion needs to classify and map them.
"""

from __future__ import annotations

import json

import pytest

from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from products.ai_observability.otel_traffic_generator import (
    plan as planmod,
    send as sendmod,
    verify as verifymod,
)

BASE_NS = 1_704_067_200_000_000_000  # fixed 2024-01-01 anchor


def test_plan_is_deterministic_for_a_seed():
    a = planmod.build_plan(seed=7, scenarios=planmod.DEFAULT_SCENARIOS, multiplier=2)
    b = planmod.build_plan(seed=7, scenarios=planmod.DEFAULT_SCENARIOS, multiplier=2)
    assert a["plan_id"] == b["plan_id"]
    assert planmod.dumps(a) == planmod.dumps(b)


def test_plan_id_changes_with_content():
    a = planmod.build_plan(seed=1, scenarios=planmod.DEFAULT_SCENARIOS, multiplier=1)
    b = planmod.build_plan(seed=2, scenarios=planmod.DEFAULT_SCENARIOS, multiplier=1)
    c = planmod.build_plan(seed=1, scenarios=planmod.DEFAULT_SCENARIOS, multiplier=2)
    assert len({a["plan_id"], b["plan_id"], c["plan_id"]}) == 3


def test_load_rejects_hand_edited_plan(tmp_path):
    plan = planmod.build_plan(seed=1, scenarios=["openai_chat"], multiplier=1)
    path = tmp_path / "plan.json"
    tampered = json.loads(planmod.dumps(plan))
    tampered["traces"][0]["spans"][0]["name"] = "edited"
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="plan_id mismatch"):
        planmod.load(str(path))


def test_expect_totals_sum_matches_traces():
    plan = planmod.build_plan(seed=0, scenarios=planmod.DEFAULT_SCENARIOS, multiplier=1)
    recomputed: dict[str, int] = {}
    for trace in plan["traces"]:
        for event, count in trace["expect_events"].items():
            recomputed[event] = recomputed.get(event, 0) + count
    assert recomputed == plan["expect_totals"]


def test_same_run_id_and_base_time_is_byte_identical():
    plan = planmod.build_plan(seed=3, scenarios=planmod.DEFAULT_SCENARIOS, multiplier=1)
    r1 = sendmod.build_requests(plan, run_id="fixed", base_time_ns=BASE_NS)
    r2 = sendmod.build_requests(plan, run_id="fixed", base_time_ns=BASE_NS)
    assert [r.SerializeToString() for r in r1] == [r.SerializeToString() for r in r2]


def test_different_run_id_yields_disjoint_trace_ids():
    plan = planmod.build_plan(seed=3, scenarios=planmod.DEFAULT_SCENARIOS, multiplier=1)
    a = set(sendmod.receipt(plan, "runA", BASE_NS, "http://x", 1)["trace_ids"])
    b = set(sendmod.receipt(plan, "runB", BASE_NS, "http://x", 1)["trace_ids"])
    assert a.isdisjoint(b)
    assert len(a) == len(plan["traces"])


def test_requests_stay_under_span_cap():
    plan = planmod.build_plan(seed=0, scenarios=planmod.DEFAULT_SCENARIOS, multiplier=8)
    for req in sendmod.build_requests(plan, run_id="r", base_time_ns=BASE_NS):
        spans = sum(len(ss.spans) for rs in req.resource_spans for ss in rs.scope_spans)
        assert spans <= sendmod.MAX_SPANS_PER_REQUEST


def test_otlp_spans_carry_classification_attributes():
    plan = planmod.build_plan(seed=0, scenarios=["openai_chat"], multiplier=1)
    req = sendmod.build_requests(plan, run_id="r", base_time_ns=BASE_NS)[0]
    # Round-trip through protobuf to prove it's wire-valid.
    reparsed = trace_service_pb2.ExportTraceServiceRequest()
    reparsed.ParseFromString(req.SerializeToString())
    spans = [sp for rs in reparsed.resource_spans for ss in rs.scope_spans for sp in ss.spans]
    gen = next(sp for sp in spans if sp.name == "chat gpt-4o")
    keys = {kv.key for kv in gen.attributes}
    assert "gen_ai.operation.name" in keys
    assert "gen_ai.usage.input_tokens" in keys
    assert "$otelgen_run_id" in keys
    # Parent/child links resolve within the trace.
    assert gen.parent_span_id != b""
    assert len(gen.trace_id) == 16 and len(gen.span_id) == 8


def test_error_span_sets_status_and_exception_event():
    plan = planmod.build_plan(seed=0, scenarios=["error_generation"], multiplier=1)
    req = sendmod.build_requests(plan, run_id="r", base_time_ns=BASE_NS)[0]
    spans = [sp for rs in req.resource_spans for ss in rs.scope_spans for sp in ss.spans]
    errored = [sp for sp in spans if sp.status.code == 2]  # STATUS_CODE_ERROR
    assert len(errored) == 1
    assert any(ev.name == "exception" for ev in errored[0].events)


def test_compare_detects_metric_drift():
    base: verifymod.VerifyResult = {
        "version": 1,
        "plan_id": "p",
        "run_id": "a",
        "ok": True,
        "observed_totals": {"$ai_generation": 10},
        "expect_totals": {"$ai_generation": 10},
        "metrics": {"sum_total_cost_usd": 0.5, "models": ["gpt-4o"]},
        "checks": [{"name": "count:$ai_generation", "ok": True, "detail": ""}],
    }
    candidate = json.loads(json.dumps(base))
    candidate["run_id"] = "b"
    same, diffs = verifymod.compare(base, candidate)
    assert same and not diffs

    candidate["observed_totals"]["$ai_generation"] = 7
    candidate["metrics"]["sum_total_cost_usd"] = 0.35
    same, diffs = verifymod.compare(base, candidate)
    assert not same
    fields = {d["field"] for d in diffs}
    assert "observed_totals.$ai_generation" in fields
    assert "metrics.sum_total_cost_usd" in fields
