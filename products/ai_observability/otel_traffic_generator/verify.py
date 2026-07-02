"""Verify ingested traffic through the PostHog Django API and compare runs.

Verification reads back the events a run produced (scoped by the run's trace ids)
and checks them against the plan's expectations, using both raw HogQL and the AI
observability product's own ``TracesQuery`` / ``TraceQuery`` runners. It emits a
*normalized* result whose ``metrics`` block is run-independent (no run id / trace
ids), so a baseline run and a post-cutover run can be diffed directly with
``compare``.
"""

from __future__ import annotations

import json
import time
from typing import Any, TypedDict

import requests

from .plan import Plan, TraceSpec
from .send import RunReceipt, span_id_bytes, trace_id_bytes

RESULT_VERSION = 1


class Check(TypedDict):
    name: str
    ok: bool
    detail: str


class VerifyResult(TypedDict):
    version: int
    plan_id: str
    run_id: str
    ok: bool
    observed_totals: dict[str, int]
    expect_totals: dict[str, int]
    metrics: dict[str, Any]
    checks: list[Check]


class _ApiError(RuntimeError):
    pass


def _query(api_host: str, project_id: str, api_key: str, query: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = f"{api_host.rstrip('/')}/api/projects/{project_id}/query/"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        # force_blocking bypasses the query result cache — without it, the first
        # (empty) poll result is cached and every later poll of the same query
        # keeps returning it even after the events have landed.
        json={"query": query, "refresh": "force_blocking"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise _ApiError(f"query failed: HTTP {resp.status_code} {resp.text[:500]}")
    data: dict[str, Any] = resp.json()
    return data


def _quote_list(values: list[str]) -> str:
    # trace ids are hex, but quote-escape defensively anyway.
    return ", ".join("'" + v.replace("'", "\\'") + "'" for v in values)


def _floor_datetime_sql(base_time_ns: int) -> str:
    # 10 min before the run's base time — comfortably covers ingestion skew while
    # keeping the scan bounded.
    floor_s = base_time_ns // 1_000_000_000 - 600
    return f"toDateTime({floor_s})"


def _count_query(trace_ids: list[str], base_time_ns: int) -> str:
    return (
        "SELECT event, count() AS cnt FROM events "
        f"WHERE properties.$ai_trace_id IN ({_quote_list(trace_ids)}) "
        f"AND timestamp > {_floor_datetime_sql(base_time_ns)} "
        "GROUP BY event"
    )


def _detail_query(trace_ids: list[str], base_time_ns: int) -> str:
    return (
        "SELECT "
        "properties.$ai_trace_id AS trace_id, "
        "properties.$ai_span_id AS span_id, "
        "event, "
        "properties.$otelgen_scenario AS scenario, "
        "toString(properties.$ai_model) AS model, "
        "toString(properties.$ai_provider) AS provider, "
        "toString(properties.$ai_ingestion_source) AS ingestion_source, "
        "toString(properties.$ai_is_error) AS is_error, "
        "toFloat(properties.$ai_input_tokens) AS input_tokens, "
        "toFloat(properties.$ai_output_tokens) AS output_tokens, "
        "toFloat(properties.$ai_total_cost_usd) AS total_cost, "
        "toFloat(properties.$ai_latency) AS latency, "
        "toFloat(properties.$ai_cache_read_input_tokens) AS cache_read_tokens "
        # $ai_input / $ai_output_choices are stripped from the `events` table by
        # the split-ai-events step and live only on ai_events — verify them via
        # TraceQuery instead (see _fetch_ai_event_props).
        "FROM events "
        f"WHERE properties.$ai_trace_id IN ({_quote_list(trace_ids)}) "
        f"AND timestamp > {_floor_datetime_sql(base_time_ns)} "
        "ORDER BY trace_id, timestamp LIMIT 5000"
    )


def _totals_from_rows(rows: list[list[Any]]) -> dict[str, int]:
    return {str(event): int(cnt) for event, cnt in rows}


def _meets(observed: dict[str, int], expected: dict[str, int]) -> bool:
    return all(observed.get(event, 0) >= count for event, count in expected.items())


def _poll_totals(
    api_host: str,
    project_id: str,
    api_key: str,
    trace_ids: list[str],
    base_time_ns: int,
    expect_totals: dict[str, int],
    timeout_s: float,
    query_timeout: float,
    log: Any,
) -> dict[str, int]:
    """Poll the count query until expectations are met or the timeout elapses."""
    deadline = time.monotonic() + timeout_s
    delay = 3.0
    observed: dict[str, int] = {}
    count_sql = _count_query(trace_ids, base_time_ns)
    while True:
        try:
            data = _query(api_host, project_id, api_key, {"kind": "HogQLQuery", "query": count_sql}, query_timeout)
            observed = _totals_from_rows(data.get("results", []))
        except _ApiError as exc:
            log(f"  query error (will retry): {exc}")
        if _meets(observed, expect_totals):
            return observed
        if time.monotonic() >= deadline:
            return observed
        log(f"  waiting for ingestion… observed={observed} expected={expect_totals}")
        time.sleep(delay)
        delay = min(delay * 1.5, 20.0)


def _needs_ai_event_props(trace: TraceSpec) -> bool:
    return any(exp.get("input_present") or exp.get("output_present") for exp in trace["expect_props"])


def _fetch_ai_event_props(
    api_host: str,
    project_id: str,
    api_key: str,
    plan: Plan,
    run_id: str,
    base_time_ns: int,
    query_timeout: float,
    log: Any,
) -> dict[str, dict[str, Any]]:
    """Map span_id (hex) -> event properties from ai_events, via TraceQuery.

    $ai_input / $ai_output_choices only exist on the ai_events table, which is
    not directly queryable in HogQL — the product's TraceQuery runner reads it.
    We query only the traces that actually have an input/output expectation.
    """
    date_from = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base_time_ns // 1_000_000_000 - 1800))
    out: dict[str, dict[str, Any]] = {}
    for trace in plan["traces"]:
        if not _needs_ai_event_props(trace):
            continue
        trace_hex = trace_id_bytes(plan["plan_id"], run_id, trace["index"]).hex()
        query = {"kind": "TraceQuery", "traceId": trace_hex, "dateRange": {"date_from": date_from}}
        try:
            data = _query(api_host, project_id, api_key, query, query_timeout)
        except _ApiError as exc:
            log(f"  TraceQuery({trace['scenario']}) error: {exc}")
            continue
        for result in data.get("results", []):
            for event in result.get("events", []):
                props = event.get("properties", {})
                span_id = props.get("$ai_span_id")
                if span_id is not None:
                    out[str(span_id)] = props
    return out


def _check_props(
    plan: Plan, run_id: str, rows: list[dict[str, Any]], ai_props: dict[str, dict[str, Any]]
) -> list[Check]:
    by_span = {str(r["span_id"]): r for r in rows}
    checks: list[Check] = []
    for trace in plan["traces"]:
        for exp in trace["expect_props"]:
            span_index = exp["span_index"]
            hex_id = span_id_bytes(plan["plan_id"], run_id, trace["index"], span_index).hex()
            label = f"{trace['scenario']}[{trace['index']}].span{span_index}"
            row = by_span.get(hex_id)
            if row is None:
                checks.append({"name": f"props:{label}", "ok": False, "detail": "event not found for span"})
                continue
            aep = ai_props.get(hex_id, {})
            failures: list[str] = []
            if "model" in exp and str(row["model"]) != exp["model"]:
                failures.append(f"$ai_model={row['model']!r} != {exp['model']!r}")
            if "provider" in exp and str(row["provider"]) != exp["provider"]:
                failures.append(f"$ai_provider={row['provider']!r} != {exp['provider']!r}")
            if "input_tokens" in exp and int(row["input_tokens"] or 0) != exp["input_tokens"]:
                failures.append(f"$ai_input_tokens={row['input_tokens']} != {exp['input_tokens']}")
            if "output_tokens" in exp and int(row["output_tokens"] or 0) != exp["output_tokens"]:
                failures.append(f"$ai_output_tokens={row['output_tokens']} != {exp['output_tokens']}")
            if exp.get("cost_positive") and float(row["total_cost"] or 0) <= 0:
                failures.append("$ai_total_cost_usd not > 0")
            if exp.get("latency_positive") and float(row["latency"] or 0) <= 0:
                failures.append("$ai_latency not > 0")
            if exp.get("input_present") and not aep.get("$ai_input"):
                failures.append("$ai_input empty (ai_events)")
            if exp.get("output_present") and not aep.get("$ai_output_choices"):
                failures.append("$ai_output_choices empty (ai_events)")
            if "cache_read_tokens" in exp and int(row["cache_read_tokens"] or 0) != exp["cache_read_tokens"]:
                failures.append(f"$ai_cache_read_input_tokens={row['cache_read_tokens']} != {exp['cache_read_tokens']}")
            if exp.get("is_error") and str(row["is_error"]).lower() != "true":
                failures.append(f"$ai_is_error={row['is_error']!r} != true")
            checks.append({"name": f"props:{label}", "ok": not failures, "detail": "; ".join(failures) or "ok"})
    return checks


def _metrics_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    costed = {"$ai_generation", "$ai_embedding"}
    sources: dict[str, int] = {}
    models: set[str] = set()
    providers: set[str] = set()
    sum_in = sum_out = 0
    sum_cost = 0.0
    costed_positive = 0
    latency_present = 0
    errors = 0
    cache_read_total = 0
    for r in rows:
        src = str(r["ingestion_source"])
        sources[src] = sources.get(src, 0) + 1
        if r["model"]:
            models.add(str(r["model"]))
        if r["provider"]:
            providers.add(str(r["provider"]))
        sum_in += int(r["input_tokens"] or 0)
        sum_out += int(r["output_tokens"] or 0)
        sum_cost += float(r["total_cost"] or 0)
        cache_read_total += int(r["cache_read_tokens"] or 0)
        if str(r["event"]) in costed and float(r["total_cost"] or 0) > 0:
            costed_positive += 1
        if float(r["latency"] or 0) > 0:
            latency_present += 1
        if str(r["is_error"]).lower() == "true":
            errors += 1
    return {
        "sum_input_tokens": sum_in,
        "sum_output_tokens": sum_out,
        "sum_total_cost_usd": round(sum_cost, 6),
        "costed_events_positive": costed_positive,
        "latency_present": latency_present,
        "errors_observed": errors,
        "cache_read_tokens_total": cache_read_total,
        "models": sorted(models),
        "providers": sorted(providers),
        "ingestion_sources": sources,
    }


def _traces_api_check(
    api_host: str,
    project_id: str,
    api_key: str,
    trace_ids: list[str],
    base_time_ns: int,
    query_timeout: float,
    log: Any,
) -> tuple[Check, Check]:
    """Exercise the product's TracesQuery (list) and TraceQuery (single) runners."""
    date_from_s = base_time_ns // 1_000_000_000 - 1800
    date_from = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(date_from_s))
    traces_query = {
        "kind": "TracesQuery",
        "dateRange": {"date_from": date_from},
        "limit": 500,
        "properties": [{"key": "$ai_trace_id", "type": "event", "operator": "exact", "value": trace_ids}],
    }
    want = set(trace_ids)
    try:
        data = _query(api_host, project_id, api_key, traces_query, query_timeout)
        results = data.get("results", [])
        matched = [t for t in results if str(t.get("id")) in want]
        list_check: Check = {
            "name": "traces_api:list",
            "ok": len(matched) > 0,
            "detail": f"TracesQuery surfaced {len(matched)}/{len(want)} of our traces",
        }
    except _ApiError as exc:
        log(f"  TracesQuery error: {exc}")
        return (
            {"name": "traces_api:list", "ok": False, "detail": f"TracesQuery failed: {exc}"},
            {"name": "traces_api:single", "ok": False, "detail": "skipped (list failed)"},
        )

    # Single-trace read of the first trace id.
    trace_query = {"kind": "TraceQuery", "traceId": trace_ids[0], "dateRange": {"date_from": date_from}}
    try:
        data = _query(api_host, project_id, api_key, trace_query, query_timeout)
        results = data.get("results", [])
        found = [t for t in results if str(t.get("id")) == trace_ids[0]]
        n_events = len(found[0].get("events", [])) if found else 0
        single_check: Check = {
            "name": "traces_api:single",
            "ok": bool(found) and n_events > 0,
            "detail": f"TraceQuery returned trace with {n_events} events" if found else "trace not found",
        }
    except _ApiError as exc:
        single_check = {"name": "traces_api:single", "ok": False, "detail": f"TraceQuery failed: {exc}"}
    return list_check, single_check


def verify(
    plan: Plan,
    receipt: RunReceipt,
    api_host: str,
    project_id: str,
    api_key: str,
    *,
    timeout_s: float = 180.0,
    query_timeout: float = 60.0,
    log: Any = print,
) -> VerifyResult:
    if plan["plan_id"] != receipt["plan_id"]:
        raise ValueError(f"plan/receipt mismatch: plan {plan['plan_id']} vs receipt {receipt['plan_id']}")

    trace_ids = receipt["trace_ids"]
    run_id = receipt["run_id"]
    base_time_ns = receipt["base_time_ns"]
    expect_totals = receipt["expect_totals"]

    log(f"Polling for {expect_totals} across {len(trace_ids)} traces (timeout {timeout_s:.0f}s)…")
    observed_totals = _poll_totals(
        api_host, project_id, api_key, trace_ids, base_time_ns, expect_totals, timeout_s, query_timeout, log
    )

    data = _query(
        api_host,
        project_id,
        api_key,
        {"kind": "HogQLQuery", "query": _detail_query(trace_ids, base_time_ns)},
        query_timeout,
    )
    columns = [str(c) for c in data.get("columns", [])]
    rows = [dict(zip(columns, r)) for r in data.get("results", [])]

    checks: list[Check] = []
    for event, count in expect_totals.items():
        got = observed_totals.get(event, 0)
        checks.append({"name": f"count:{event}", "ok": got >= count, "detail": f"observed {got}, expected {count}"})

    ai_props = _fetch_ai_event_props(api_host, project_id, api_key, plan, run_id, base_time_ns, query_timeout, log)
    checks.extend(_check_props(plan, run_id, rows, ai_props))

    metrics = _metrics_from_rows(rows)
    non_otel = {k: v for k, v in metrics["ingestion_sources"].items() if k != "otel"}
    checks.append(
        {
            "name": "ingestion_source:otel",
            "ok": not non_otel,
            "detail": f"non-otel sources: {non_otel}" if non_otel else "all otel",
        }
    )

    list_check, single_check = _traces_api_check(
        api_host, project_id, api_key, trace_ids, base_time_ns, query_timeout, log
    )
    checks.extend([list_check, single_check])

    ok = all(c["ok"] for c in checks)
    return {
        "version": RESULT_VERSION,
        "plan_id": plan["plan_id"],
        "run_id": run_id,
        "ok": ok,
        "observed_totals": observed_totals,
        "expect_totals": expect_totals,
        "metrics": metrics,
        "checks": checks,
    }


def dumps_result(result: VerifyResult) -> str:
    return json.dumps(result, indent=2, sort_keys=True)


def load_result(path: str) -> VerifyResult:
    with open(path, encoding="utf-8") as f:
        data: Any = json.load(f)
    return data


# ----- comparison -----------------------------------------------------------


class Diff(TypedDict):
    field: str
    baseline: Any
    candidate: Any


def compare(baseline: VerifyResult, candidate: VerifyResult) -> tuple[bool, list[Diff]]:
    """Diff two runs on their run-independent surfaces. Identical plan + healthy
    pipeline on both sides => no diffs. Any diff is attributable to the change
    between the two runs (e.g. the AI sink cutover)."""
    diffs: list[Diff] = []

    if baseline["plan_id"] != candidate["plan_id"]:
        diffs.append({"field": "plan_id", "baseline": baseline["plan_id"], "candidate": candidate["plan_id"]})

    def cmp(field: str, a: Any, b: Any) -> None:
        if a != b:
            diffs.append({"field": field, "baseline": a, "candidate": b})

    for event in sorted(set(baseline["expect_totals"]) | set(candidate["expect_totals"])):
        cmp(
            f"observed_totals.{event}",
            baseline["observed_totals"].get(event, 0),
            candidate["observed_totals"].get(event, 0),
        )

    bm, cm = baseline["metrics"], candidate["metrics"]
    for key in sorted(set(bm) | set(cm)):
        cmp(f"metrics.{key}", bm.get(key), cm.get(key))

    b_checks = {c["name"]: c["ok"] for c in baseline["checks"]}
    c_checks = {c["name"]: c["ok"] for c in candidate["checks"]}
    for name in sorted(set(b_checks) | set(c_checks)):
        cmp(f"check.{name}", b_checks.get(name), c_checks.get(name))

    return (not diffs, diffs)
