"""Resolve a plan into OTLP protobuf and POST it to ``/i/v0/ai/otel``.

Concrete trace/span IDs and event timestamps are *not* in the plan — they are
derived here from ``(plan_id, run_id)`` and the run's base time. So a given
``(plan, run_id, base_time)`` produces byte-identical requests every time
(idempotent), while a fresh ``run_id`` yields an independently-scoped run whose
events never collide with a previous run's — which is exactly what lets a
baseline run and a post-cutover run be compared.
"""

from __future__ import annotations

import json
import hashlib
from typing import Any, TypedDict

import requests
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.resource.v1 import resource_pb2
from opentelemetry.proto.trace.v1 import trace_pb2

from .plan import AttrVal, Plan, SpanSpec, TraceSpec

OTEL_PATH = "/i/v0/ai/otel"
# Server rejects >100 AI spans per request; stay well under so mixed batches fit.
MAX_SPANS_PER_REQUEST = 90
RUN_RECEIPT_VERSION = 1


class RunReceipt(TypedDict):
    version: int
    plan_id: str
    run_id: str
    base_time_ns: int
    capture_host: str
    # hex trace ids actually sent, in plan trace order — the scope key for verify.
    trace_ids: list[str]
    distinct_ids: list[str]
    sent_spans: int
    sent_requests: int
    # Echo of the plan's expectations so verify/compare need only the receipt.
    expect_totals: dict[str, int]


def _digest(*parts: str, size: int) -> bytes:
    return hashlib.blake2b("\x00".join(parts).encode("utf-8"), digest_size=size).digest()


def trace_id_bytes(plan_id: str, run_id: str, trace_index: int) -> bytes:
    return _digest(plan_id, run_id, "trace", str(trace_index), size=16)


def span_id_bytes(plan_id: str, run_id: str, trace_index: int, span_index: int) -> bytes:
    return _digest(plan_id, run_id, "span", str(trace_index), str(span_index), size=8)


def _any_value(av: AttrVal) -> common_pb2.AnyValue:
    t, v = av["t"], av["v"]
    out = common_pb2.AnyValue()
    if t == "str":
        out.string_value = v
    elif t == "int":
        out.int_value = int(v)
    elif t == "double":
        out.double_value = float(v)
    elif t == "bool":
        out.bool_value = bool(v)
    elif t == "json":
        out.string_value = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    else:
        raise ValueError(f"unknown attr type {t!r}")
    return out


def _kv(key: str, av: AttrVal) -> common_pb2.KeyValue:
    return common_pb2.KeyValue(key=key, value=_any_value(av))


def _build_span(
    span: SpanSpec,
    plan: Plan,
    trace: TraceSpec,
    run_id: str,
    base_time_ns: int,
) -> trace_pb2.Span:
    plan_id = plan["plan_id"]
    pb = trace_pb2.Span()
    pb.trace_id = trace_id_bytes(plan_id, run_id, trace["index"])
    pb.span_id = span_id_bytes(plan_id, run_id, trace["index"], span["index"])
    if span["parent_index"] is not None:
        pb.parent_span_id = span_id_bytes(plan_id, run_id, trace["index"], span["parent_index"])
    pb.name = span["name"]
    pb.start_time_unix_nano = base_time_ns + span["start_offset_ns"]
    pb.end_time_unix_nano = base_time_ns + span["end_offset_ns"]

    for key, av in span["attributes"].items():
        pb.attributes.append(_kv(key, av))
    # Run marker so events are also findable in the UI without knowing trace ids.
    pb.attributes.append(_kv("$otelgen_run_id", {"t": "str", "v": run_id}))
    pb.attributes.append(_kv("$otelgen_scenario", {"t": "str", "v": trace["scenario"]}))

    error = span["error"]
    if error is not None:
        pb.status.code = trace_pb2.Status.StatusCode.STATUS_CODE_ERROR
        pb.status.message = error["message"]
        event = pb.events.add()
        event.name = "exception"
        event.time_unix_nano = pb.end_time_unix_nano
        event.attributes.append(_kv("exception.type", {"t": "str", "v": error["exception_type"]}))
        event.attributes.append(_kv("exception.message", {"t": "str", "v": error["exception_message"]}))
        event.attributes.append(_kv("http.response.status_code", {"t": "int", "v": error["http_status"]}))
    return pb


def _resource_spans(
    trace: TraceSpec,
    plan: Plan,
    run_id: str,
    base_time_ns: int,
) -> trace_pb2.ResourceSpans:
    rs = trace_pb2.ResourceSpans()
    rs.resource.CopyFrom(
        resource_pb2.Resource(
            attributes=[
                _kv("service.name", {"t": "str", "v": "otel-ai-traffic-generator"}),
                _kv("posthog.distinct_id", {"t": "str", "v": f"{run_id}:{trace['distinct_id']}"}),
            ]
        )
    )
    scope = rs.scope_spans.add()
    for span in trace["spans"]:
        scope.spans.append(_build_span(span, plan, trace, run_id, base_time_ns))
    return rs


def build_requests(plan: Plan, run_id: str, base_time_ns: int) -> list[trace_service_pb2.ExportTraceServiceRequest]:
    """Chunk the plan's traces into OTLP requests, each under the span cap.

    A whole trace is kept in one request so parent/child links never split.
    """
    requests_out: list[trace_service_pb2.ExportTraceServiceRequest] = []
    current = trace_service_pb2.ExportTraceServiceRequest()
    current_spans = 0
    for trace in plan["traces"]:
        n = len(trace["spans"])
        if current_spans and current_spans + n > MAX_SPANS_PER_REQUEST:
            requests_out.append(current)
            current = trace_service_pb2.ExportTraceServiceRequest()
            current_spans = 0
        current.resource_spans.append(_resource_spans(trace, plan, run_id, base_time_ns))
        current_spans += n
    if current_spans:
        requests_out.append(current)
    return requests_out


def receipt(plan: Plan, run_id: str, base_time_ns: int, capture_host: str, sent_requests: int) -> RunReceipt:
    plan_id = plan["plan_id"]
    trace_ids = [trace_id_bytes(plan_id, run_id, t["index"]).hex() for t in plan["traces"]]
    distinct_ids = [f"{run_id}:{t['distinct_id']}" for t in plan["traces"]]
    sent_spans = sum(len(t["spans"]) for t in plan["traces"])
    return {
        "version": RUN_RECEIPT_VERSION,
        "plan_id": plan_id,
        "run_id": run_id,
        "base_time_ns": base_time_ns,
        "capture_host": capture_host,
        "trace_ids": trace_ids,
        "distinct_ids": distinct_ids,
        "sent_spans": sent_spans,
        "sent_requests": sent_requests,
        "expect_totals": plan["expect_totals"],
    }


def send(
    plan: Plan,
    run_id: str,
    base_time_ns: int,
    capture_host: str,
    token: str,
    *,
    timeout: float = 30.0,
    session: requests.Session | None = None,
) -> RunReceipt:
    """Build and POST every request for this run, then return the receipt."""
    reqs = build_requests(plan, run_id, base_time_ns)
    url = capture_host.rstrip("/") + OTEL_PATH
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/x-protobuf"}
    sess = session or requests.Session()
    for idx, req in enumerate(reqs):
        body = req.SerializeToString()
        resp = sess.post(url, data=body, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(
                f"OTel ingest request {idx + 1}/{len(reqs)} failed: HTTP {resp.status_code} {resp.text[:500]}"
            )
    return receipt(plan, run_id, base_time_ns, capture_host, len(reqs))


def dumps_receipt(r: RunReceipt) -> str:
    return json.dumps(r, indent=2, sort_keys=True)


def load_receipt(path: str) -> RunReceipt:
    with open(path, encoding="utf-8") as f:
        data: Any = json.load(f)
    return data
