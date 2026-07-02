"""Command-line entry point: plan -> run -> verify -> compare.

    python -m products.ai_observability.otel_traffic_generator plan   ...
    python -m products.ai_observability.otel_traffic_generator run    ...
    python -m products.ai_observability.otel_traffic_generator verify ...
    python -m products.ai_observability.otel_traffic_generator compare ...

Config is read from flags, falling back to env vars (POSTHOG_OTEL_TOKEN,
POSTHOG_PERSONAL_API_KEY, POSTHOG_PROJECT_ID, POSTHOG_CLOUD).
"""

from __future__ import annotations

import os
import sys
import time
import secrets
import argparse
from calendar import timegm
from typing import Any

from . import (
    plan as planmod,
    send as sendmod,
    verify as verifymod,
)

# capture (ingest) host, app (API) host
CLOUD_HOSTS: dict[str, tuple[str, str]] = {
    "us": ("https://us.i.posthog.com", "https://us.posthog.com"),
    "eu": ("https://eu.i.posthog.com", "https://eu.posthog.com"),
    "local": ("http://localhost:8010", "http://localhost:8010"),
}


def _resolve_hosts(args: argparse.Namespace) -> tuple[str, str]:
    cloud = args.cloud or os.environ.get("POSTHOG_CLOUD", "us")
    if cloud not in CLOUD_HOSTS:
        raise SystemExit(f"unknown --cloud {cloud!r}; choose from {sorted(CLOUD_HOSTS)}")
    capture_default, api_default = CLOUD_HOSTS[cloud]
    capture_host = getattr(args, "capture_host", None) or capture_default
    api_host = getattr(args, "api_host", None) or api_default
    return capture_host, api_host


def _base_time_ns(raw: str) -> int:
    if raw == "now":
        return time.time_ns()
    # Accept ISO8601 UTC like 2026-07-02T10:00:00Z.
    parsed = time.strptime(raw.replace("Z", "GMT"), "%Y-%m-%dT%H:%M:%S%Z")
    return timegm(parsed) * 1_000_000_000


def _cmd_plan(args: argparse.Namespace) -> int:
    scenarios = args.scenarios.split(",") if args.scenarios else planmod.DEFAULT_SCENARIOS
    plan = planmod.build_plan(seed=args.seed, scenarios=scenarios, multiplier=args.multiplier)
    text = planmod.dumps(plan)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        n_spans = sum(len(t["spans"]) for t in plan["traces"])
        print(f"Wrote plan {plan['plan_id']} to {args.out}")
        print(f"  {len(plan['traces'])} traces, {n_spans} spans, expect_totals={plan['expect_totals']}")
    else:
        print(text)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    plan = planmod.load(args.plan)
    capture_host, api_host = _resolve_hosts(args)
    token = args.token or os.environ.get("POSTHOG_OTEL_TOKEN")
    if not token:
        raise SystemExit("missing ingest token: pass --token or set POSTHOG_OTEL_TOKEN (public phc_ project key)")
    run_id = args.run_id or secrets.token_hex(4)
    base_time_ns = _base_time_ns(args.base_time)

    if args.dry_run:
        reqs = sendmod.build_requests(plan, run_id, base_time_ns)
        n_bytes = sum(len(r.SerializeToString()) for r in reqs)
        rec = sendmod.receipt(plan, run_id, base_time_ns, capture_host, len(reqs))
        print(f"[dry-run] plan {plan['plan_id']} run {run_id}")
        print(
            f"[dry-run] would POST {len(reqs)} request(s), {rec['sent_spans']} spans, {n_bytes} bytes to {capture_host}{sendmod.OTEL_PATH}"
        )
        _write_receipt(args, rec)
        return 0

    print(f"Sending plan {plan['plan_id']} as run {run_id} -> {capture_host}{sendmod.OTEL_PATH}")
    rec = sendmod.send(plan, run_id, base_time_ns, capture_host, token)
    print(f"  sent {rec['sent_spans']} spans in {rec['sent_requests']} request(s)")
    _write_receipt(args, rec)

    if args.verify:
        return _run_verify(args, plan, rec, api_host)
    print(f"Verify later with: verify --plan {args.plan} --run {_receipt_path(args, rec)}")
    return 0


def _receipt_path(args: argparse.Namespace, rec: sendmod.RunReceipt) -> str:
    return args.out or f"run-{rec['run_id']}.json"


def _write_receipt(args: argparse.Namespace, rec: sendmod.RunReceipt) -> None:
    path = _receipt_path(args, rec)
    with open(path, "w", encoding="utf-8") as f:
        f.write(sendmod.dumps_receipt(rec) + "\n")
    print(f"  wrote run receipt to {path}")


def _run_verify(args: argparse.Namespace, plan: planmod.Plan, rec: sendmod.RunReceipt, api_host: str) -> int:
    api_key = args.api_key or os.environ.get("POSTHOG_PERSONAL_API_KEY")
    project_id = args.project_id or os.environ.get("POSTHOG_PROJECT_ID")
    if not api_key or not project_id:
        raise SystemExit("verify needs --api-key (personal key, query:read) and --project-id")
    result = verifymod.verify(
        plan, rec, api_host, project_id, api_key, timeout_s=args.timeout, query_timeout=args.query_timeout
    )
    out = args.result_out or f"result-{rec['run_id']}.json"
    with open(out, "w", encoding="utf-8") as f:
        f.write(verifymod.dumps_result(result) + "\n")
    _print_result(result, out)
    return 0 if result["ok"] else 1


def _cmd_verify(args: argparse.Namespace) -> int:
    plan = planmod.load(args.plan)
    rec = sendmod.load_receipt(args.run)
    _, api_host = _resolve_hosts(args)
    return _run_verify(args, plan, rec, api_host)


def _print_result(result: verifymod.VerifyResult, out_path: str) -> None:
    status = "PASS" if result["ok"] else "FAIL"
    print(f"\n=== verify {status} — run {result['run_id']} ===")
    print(f"observed_totals: {result['observed_totals']}  expected: {result['expect_totals']}")
    m = result["metrics"]
    print(
        f"metrics: cost=${m['sum_total_cost_usd']} tokens_in={m['sum_input_tokens']} "
        f"tokens_out={m['sum_output_tokens']} costed+={m['costed_events_positive']} "
        f"errors={m['errors_observed']} models={m['models']}"
    )
    for c in result["checks"]:
        mark = "ok  " if c["ok"] else "FAIL"
        print(f"  [{mark}] {c['name']}: {c['detail']}")
    print(f"result written to {out_path}")


def _cmd_compare(args: argparse.Namespace) -> int:
    baseline = verifymod.load_result(args.baseline)
    candidate = verifymod.load_result(args.candidate)
    same, diffs = verifymod.compare(baseline, candidate)
    print(f"baseline run {baseline['run_id']} vs candidate run {candidate['run_id']}")
    if same:
        print("MATCH — no differences on the run-independent surface (totals, metrics, checks)")
        return 0
    print(f"DIFFERENCES ({len(diffs)}):")
    for d in diffs:
        print(f"  {d['field']}: baseline={d['baseline']!r}  candidate={d['candidate']!r}")
    return 1


def _add_host_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cloud", choices=sorted(CLOUD_HOSTS), help="host preset (default us, or POSTHOG_CLOUD)")
    p.add_argument("--capture-host", help="override OTel ingest host")
    p.add_argument("--api-host", help="override Django API host")


def _add_verify_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--api-key", help="personal API key with query:read (or POSTHOG_PERSONAL_API_KEY)")
    p.add_argument("--project-id", help="numeric project/team id (or POSTHOG_PROJECT_ID)")
    p.add_argument("--timeout", type=float, default=180.0, help="seconds to poll for ingestion (default 180)")
    p.add_argument("--query-timeout", type=float, default=60.0, help="per-query HTTP timeout (default 60)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="otel-ai-traffic-generator", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="build a deterministic plan")
    p_plan.add_argument("--seed", type=int, default=0)
    p_plan.add_argument("--multiplier", type=int, default=1, help="repeat each scenario N times (more volume)")
    p_plan.add_argument("--scenarios", help=f"comma-separated subset of: {','.join(planmod.DEFAULT_SCENARIOS)}")
    p_plan.add_argument("--out", help="write plan JSON here (default: stdout)")
    p_plan.set_defaults(func=_cmd_plan)

    p_run = sub.add_parser("run", help="send a plan's traffic to the OTel endpoint")
    p_run.add_argument("--plan", required=True, help="plan JSON path")
    p_run.add_argument("--token", help="public project token, phc_… (or POSTHOG_OTEL_TOKEN)")
    p_run.add_argument("--run-id", help="scope id; pass a fixed value for byte-identical repeat runs")
    p_run.add_argument("--base-time", default="now", help="'now' (default) or ISO8601 UTC anchor for span timestamps")
    p_run.add_argument("--out", help="run receipt path (default run-<run_id>.json)")
    p_run.add_argument("--dry-run", action="store_true", help="build & summarize requests without sending")
    p_run.add_argument("--verify", action="store_true", help="verify immediately after sending")
    p_run.add_argument("--result-out", help="verify result path when --verify (default result-<run_id>.json)")
    _add_host_args(p_run)
    _add_verify_args(p_run)
    p_run.set_defaults(func=_cmd_run)

    p_verify = sub.add_parser("verify", help="verify an already-sent run via the PostHog API")
    p_verify.add_argument("--plan", required=True, help="plan JSON path")
    p_verify.add_argument("--run", required=True, help="run receipt JSON path")
    p_verify.add_argument("--result-out", help="verify result path (default result-<run_id>.json)")
    _add_host_args(p_verify)
    _add_verify_args(p_verify)
    p_verify.set_defaults(func=_cmd_verify)

    p_compare = sub.add_parser("compare", help="diff two verify results (baseline vs candidate)")
    p_compare.add_argument("--baseline", required=True)
    p_compare.add_argument("--candidate", required=True)
    p_compare.set_defaults(func=_cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Any = args.func
    return int(func(args))


if __name__ == "__main__":
    sys.exit(main())
