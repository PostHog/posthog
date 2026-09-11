#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Score a semantic-layer canary batch deterministically from its full session logs.

Reads the runner's `CanaryRunResult` JSON, fetches every scored run's complete ACP session
log, and grades each case with the same scorers the offline evals use. Emits one JSON verdict
row per case, and optionally `$ai_evaluation` events tagged with the canary run id.

Usage:
    python semantic_layer_canary_score.py --results run.json
    python semantic_layer_canary_score.py --results - --emit

Environment:
    POSTHOG_API_KEY        personal API key with task:read on the target project
    POSTHOG_CAPTURE_TOKEN  project API token, required only with --emit
"""

from __future__ import annotations

import os
import sys
import json
import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from products.data_catalog.evals.scorers import (
    CanonicalMetricRun,
    ClarificationAsked,
    MetricDescribeBeforeAdaptedSql,
    MetricsCatalogBeforeDataDiscovery,
    ProposedMetricNotRun,
)
from products.posthog_ai.eval_harness.scorers.contract import Scorer

DEFAULT_HOST = "https://us.posthog.com"
DEFAULT_PROJECT_ID = 2
SESSION_LOG_PAGE_SIZE = 5_000
MAX_SESSION_LOG_PAGES = 200
REQUEST_TIMEOUT_SECONDS = 120.0
EVALUATION_METRIC_NAME = "semantic_layer_canary_routing"

CANONICAL_ROUTING = "canonical_metric"
CLARIFY_ROUTING = "clarify"
NO_MATCH_ROUTING = "no_match"
DERIVE_ROUTING = "derive_from_approved"

HARD_CHECKS = frozenset(
    {
        "metrics_catalog_before_data_discovery",
        "canonical_metric_run",
        "clarification_asked",
        "proposed_metric_not_run",
    }
)

SCORERS: list[Scorer] = [
    MetricsCatalogBeforeDataDiscovery(),
    CanonicalMetricRun(),
    ClarificationAsked(),
    ProposedMetricNotRun(),
    MetricDescribeBeforeAdaptedSql(),
]


class UnknownRouting(ValueError):
    pass


def expectations_for(routing: str, expected_metric: str | None) -> dict[str, Any]:
    if routing == CLARIFY_ROUTING:
        return {"clarification_asked": {}, "canonical_metric_run": {"outcome": "not_called"}}
    if routing == NO_MATCH_ROUTING:
        return {
            "metrics_catalog_before_data_discovery": {},
            "canonical_metric_run": {"outcome": "not_called"},
        }
    if routing in (CANONICAL_ROUTING, DERIVE_ROUTING):
        if not expected_metric:
            raise UnknownRouting(f"routing '{routing}' needs an expected_metric")
        expectations: dict[str, Any] = {
            "metrics_catalog_before_data_discovery": {},
            "canonical_metric_run": {"metric_name": expected_metric, "outcome": "succeeded"},
            "metric_describe_before_adapted_sql": {},
        }
        if routing == DERIVE_ROUTING:
            expectations["proposed_metric_not_run"] = {"metric_name": expected_metric}
        return expectations
    raise UnknownRouting(routing)


class SessionLogClient:
    def __init__(self, *, host: str, project_id: int, api_key: str, transport: httpx.BaseTransport | None = None):
        self.project_id = project_id
        self._client = httpx.Client(
            base_url=host.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport,
        )

    def __enter__(self) -> SessionLogClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._client.close()

    def read_full_log(self, task_id: str, run_id: str) -> str:
        entries: list[dict] = []
        offset = 0
        for _page in range(MAX_SESSION_LOG_PAGES):
            response = self._client.get(
                f"/api/projects/{self.project_id}/tasks/{task_id}/runs/{run_id}/session_logs/",
                params={"limit": SESSION_LOG_PAGE_SIZE, "offset": offset},
            )
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, list):
                raise ValueError(f"unexpected session_logs payload for run {run_id}")
            entries.extend(page)
            if response.headers.get("X-Has-More") != "true" or not page:
                break
            offset += len(page)
        else:
            raise ValueError(f"session log for run {run_id} exceeded {MAX_SESSION_LOG_PAGES} pages")
        return "\n".join(json.dumps(entry) for entry in entries)


def score_case(case: dict[str, Any], raw_log: str) -> dict[str, Any]:
    routing = case.get("expected_routing") or ""
    row: dict[str, Any] = {
        "case_id": case.get("case_id"),
        "category": case.get("category"),
        "expected_metric": case.get("expected_metric"),
        "expected_routing": routing,
        "task_id": case.get("task_id"),
        "task_run_id": case.get("task_run_id"),
        "task_url": case.get("task_url"),
        "clarification_questions": case.get("clarification_questions") or [],
    }
    if case.get("status") != "completed":
        return row | {"verdict": "unscored", "reason": "run did not reach a confirmed terminal status"}
    try:
        expectations = expectations_for(routing, case.get("expected_metric"))
    except UnknownRouting as error:
        return row | {"verdict": "unscored", "reason": f"unrecognized expected_routing: {error}"}

    output = {"raw_log": raw_log, "prompt": case.get("question", "") or ""}
    scores = [scorer.eval(output, expectations) for scorer in SCORERS]
    checks = {score.name: score.score for score in scores if score.score is not None}
    failed_hard = sorted(name for name, value in checks.items() if name in HARD_CHECKS and value < 1.0)
    failed_soft = sorted(name for name, value in checks.items() if name not in HARD_CHECKS and value < 1.0)
    return row | {
        "verdict": "fail" if failed_hard else "pass",
        "checks": checks,
        "failed_checks": failed_hard,
        "advisory_checks": failed_soft,
        "metadata": {score.name: score.metadata for score in scores if score.score is not None},
    }


def emit_evaluation_event(*, host: str, capture_token: str, run_id: str, row: dict[str, Any]) -> None:
    if row["verdict"] == "unscored":
        return
    properties = {
        "$ai_experiment_id": run_id,
        "$ai_experiment_name": "semantic-layer-canary",
        "$ai_experiment_item_id": f"{run_id}:{row['case_id']}",
        "$ai_experiment_item_name": row["case_id"],
        "$ai_metric_name": EVALUATION_METRIC_NAME,
        "$ai_metric_version": "1",
        "$ai_status": "completed",
        "$ai_result_type": "boolean",
        "$ai_reasoning": json.dumps({"failed": row["failed_checks"], "advisory": row["advisory_checks"]}),
        "$ai_expected": row["expected_routing"],
        "$ai_score": 1 if row["verdict"] == "pass" else 0,
        "$ai_score_min": 0,
        "$ai_score_max": 1,
        "$ai_evaluation_applicable": True,
    }
    response = httpx.post(
        f"{host.replace('us.posthog.com', 'us.i.posthog.com').rstrip('/')}/i/v0/e/",
        json={
            "api_key": capture_token,
            "event": "$ai_evaluation",
            "distinct_id": f"semantic-layer-canary:{run_id}",
            "properties": properties,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, help="Runner result JSON, or - for stdin")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--project-id", type=int, default=DEFAULT_PROJECT_ID)
    parser.add_argument("--case-id", action="append", dest="case_ids", default=[])
    parser.add_argument("--emit", action="store_true", help="Publish an $ai_evaluation event per scored case")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    raw_results = sys.stdin.read() if args.results == "-" else open(args.results).read()
    results = json.loads(raw_results)
    run_id = results["run_id"]
    cases = [case for case in results["cases"] if not args.case_ids or case["case_id"] in args.case_ids]

    api_key = os.environ.get("POSTHOG_API_KEY")
    if not api_key:
        print("POSTHOG_API_KEY is required", file=sys.stderr)
        return 2
    capture_token = os.environ.get("POSTHOG_CAPTURE_TOKEN")
    if args.emit and not capture_token:
        print("POSTHOG_CAPTURE_TOKEN is required with --emit", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    with SessionLogClient(host=args.host, project_id=args.project_id, api_key=api_key) as client:
        for case in cases:
            task_id, run = case.get("task_id"), case.get("task_run_id")
            raw_log = client.read_full_log(task_id, run) if task_id and run else ""
            row = score_case(case, raw_log)
            rows.append(row)
            print(json.dumps(row))
            if args.emit and capture_token:
                emit_evaluation_event(host=args.host, capture_token=capture_token, run_id=run_id, row=row)

    scored = [row for row in rows if row["verdict"] != "unscored"]
    passed = sum(row["verdict"] == "pass" for row in scored)
    print(
        json.dumps(
            {
                "run_id": run_id,
                "scored": len(scored),
                "passed": passed,
                "failed": len(scored) - passed,
                "unscored": len(rows) - len(scored),
            }
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
