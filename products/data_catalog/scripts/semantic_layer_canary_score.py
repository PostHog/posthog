#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Score a semantic-layer canary batch deterministically from its full session logs.

Reads the runner's `CanaryRunResult` JSON, or rebuilds the batch from the Tasks API and a pinned
dataset revision, fetches every scored run's complete ACP session log, and grades each case with
the same scorers the offline evals use. Emits one JSON verdict row per case, and optionally
`$ai_evaluation` events tagged with the batch id.

Usage:
    python semantic_layer_canary_score.py --results run.json
    python semantic_layer_canary_score.py --batch 2026-09-10T16:54:23Z 2026-09-10T17:17:23Z --revision 42 --emit

Environment:
    POSTHOG_API_KEY        personal API key with task:read, plus dataset:read for --batch
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
from pydantic import BaseModel, ConfigDict

from products.data_catalog.evals.scorers import (
    CanonicalMetricRun,
    ClarificationAsked,
    MetricDescribeBeforeAdaptedSql,
    MetricsCatalogBeforeDataDiscovery,
    ProposedMetricNotRun,
)
from products.data_catalog.scripts.semantic_layer_canary import (
    DATASET_ITEMS_PATH,
    DATASETS_PATH,
    DEFAULT_DATASET_NAME,
    CanaryCase,
    CanaryError,
    ClarificationRequested,
    DatasetSnapshot,
    dataset_items_params,
    dataset_search_params,
    is_completed_turn,
    parse_dataset_item_page,
    select_dataset,
)
from products.posthog_ai.eval_harness.scorers.contract import Scorer

DEFAULT_HOST = "https://us.posthog.com"
DEFAULT_PROJECT_ID = 2
SESSION_LOG_PAGE_SIZE = 5_000
MAX_SESSION_LOG_PAGES = 200
TASK_LIST_PAGE_SIZE = 50
TASK_RUN_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 120.0
EVALUATION_METRIC_NAME = "semantic_layer_canary_routing"
EXPERIMENT_NAME = "semantic-layer-canary"
BATCH_ID_PREFIX = "tasks"
CANARY_ORIGIN_PRODUCT = "posthog_ai"
PERMISSION_REQUEST_METHOD = "session/request_permission"

CANONICAL_ROUTING = "canonical_metric"
CLARIFY_ROUTING = "clarify"
NO_MATCH_ROUTING = "no_match"
DERIVE_ROUTING = "derive_from_approved"

COMPLETED_STATUS = "completed"
CANCELLED_STATUS = "cancelled"
FAILED_STATUS = "failed"
MISSING_STATUS = "missing"
INCOMPLETE_STATUS = "incomplete"
DUPLICATE_STATUS = "duplicate"
UNSCORED_VERDICT = "unscored"
TERMINAL_RUN_STATUSES = frozenset({COMPLETED_STATUS, CANCELLED_STATUS, FAILED_STATUS})

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


class BatchWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime

    @property
    def batch_id(self) -> str:
        return f"{BATCH_ID_PREFIX}:{_utc_iso(self.start)}:{_utc_iso(self.end)}"

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


class _TaskSummary(BaseModel):
    id: str
    description: str = ""
    created_at: datetime


class _TaskPage(BaseModel):
    next: str | None = None
    results: list[_TaskSummary]


class _TaskRun(BaseModel):
    id: str
    status: str
    created_at: datetime


class _TaskRunPage(BaseModel):
    results: list[_TaskRun]


class _BatchAttempt(BaseModel):
    task_id: str
    run: _TaskRun


def _utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_batch_moment(raw: str) -> datetime:
    moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


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


class CanaryApiClient:
    def __init__(self, *, host: str, project_id: int, api_key: str, transport: httpx.BaseTransport | None = None):
        self.host = host.rstrip("/")
        self.project_id = project_id
        self._client = httpx.Client(
            base_url=self.host,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport,
        )
        self._log_entries: dict[tuple[str, str], list[dict]] = {}

    def __enter__(self) -> CanaryApiClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._client.close()

    def read_log_entries(self, task_id: str, run_id: str) -> list[dict]:
        cached = self._log_entries.get((task_id, run_id))
        if cached is not None:
            return cached
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
        self._log_entries[(task_id, run_id)] = entries
        return entries

    def read_full_log(self, task_id: str, run_id: str) -> str:
        return "\n".join(json.dumps(entry) for entry in self.read_log_entries(task_id, run_id))

    def load_dataset_snapshot(self, dataset_name: str, revision: int) -> DatasetSnapshot:
        response = self._client.get(
            DATASETS_PATH.format(project_id=self.project_id), params=dataset_search_params(dataset_name)
        )
        response.raise_for_status()
        dataset = select_dataset(response.json(), dataset_name)
        cases: list[CanaryCase] = []
        seen_case_ids: set[str] = set()
        offset = 0
        while True:
            items_response = self._client.get(
                DATASET_ITEMS_PATH.format(project_id=self.project_id),
                params=dataset_items_params(dataset.id, revision, offset),
            )
            items_response.raise_for_status()
            page = parse_dataset_item_page(items_response.json(), seen_case_ids)
            cases.extend(page.cases)
            if page.next_page is None:
                return DatasetSnapshot(dataset_id=dataset.id, dataset_name=dataset.name, revision=revision, cases=cases)
            offset += page.item_count

    def find_tasks(self, question: str, window: BatchWindow) -> list[_TaskSummary]:
        matches: list[_TaskSummary] = []
        url: str | None = f"/api/projects/{self.project_id}/tasks/"
        params: dict[str, str | int] | None = {
            "origin_product": CANARY_ORIGIN_PRODUCT,
            "search": question,
            "ordering": "-created_at",
            "limit": TASK_LIST_PAGE_SIZE,
        }
        while url:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            page = _TaskPage.model_validate(response.json())
            matches.extend(
                task for task in page.results if task.description == question and window.contains(task.created_at)
            )
            reached_window_start = any(task.created_at < window.start for task in page.results)
            url, params = (None, None) if reached_window_start else (page.next, None)
        return matches

    def list_runs(self, task_id: str) -> list[_TaskRun]:
        response = self._client.get(
            f"/api/projects/{self.project_id}/tasks/{task_id}/runs/", params={"limit": TASK_RUN_PAGE_SIZE}
        )
        response.raise_for_status()
        return _TaskRunPage.model_validate(response.json()).results

    def task_url(self, task_id: str, run_id: str) -> str:
        return f"{self.host}/project/{self.project_id}/tasks/{task_id}?runId={run_id}"


def _as_stream_payload(entry: dict) -> dict:
    notification = entry.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != PERMISSION_REQUEST_METHOD:
        return entry
    return {"type": "permission_request", **(notification.get("params") or {})}


def clarification_questions(entries: Sequence[dict]) -> list[str] | None:
    for entry in entries:
        try:
            is_completed_turn(_as_stream_payload(entry))
        except ClarificationRequested as clarification:
            return clarification.questions
        except CanaryError:
            continue
    return None


def _winning_attempts(
    client: CanaryApiClient, attempts: Sequence[_BatchAttempt]
) -> list[tuple[_BatchAttempt, list[str]]]:
    winners: list[tuple[_BatchAttempt, list[str]]] = []
    for attempt in attempts:
        if attempt.run.status == COMPLETED_STATUS:
            winners.append((attempt, []))
        elif attempt.run.status == CANCELLED_STATUS:
            questions = clarification_questions(client.read_log_entries(attempt.task_id, attempt.run.id))
            if questions is not None:
                winners.append((attempt, questions))
    return winners


def _attempt_fields(client: CanaryApiClient, attempt: _BatchAttempt) -> dict[str, Any]:
    return {
        "task_id": attempt.task_id,
        "task_run_id": attempt.run.id,
        "task_url": client.task_url(attempt.task_id, attempt.run.id),
    }


def reconstruct_case(client: CanaryApiClient, case: CanaryCase, window: BatchWindow) -> dict[str, Any]:
    row: dict[str, Any] = {
        "case_id": case.case_id,
        "category": case.category,
        "expected_metric": case.expected_metric,
        "expected_routing": case.expected_routing,
        "question": case.question,
        "task_id": None,
        "task_run_id": None,
        "task_url": None,
        "clarification_questions": [],
    }
    attempts = sorted(
        (
            _BatchAttempt(task_id=task.id, run=run)
            for task in client.find_tasks(case.question, window)
            for run in client.list_runs(task.id)
        ),
        key=lambda attempt: attempt.run.created_at,
    )
    if not attempts:
        return row | {"status": MISSING_STATUS}
    winners = _winning_attempts(client, attempts)
    if len(winners) > 1:
        return row | _attempt_fields(client, attempts[-1]) | {"status": DUPLICATE_STATUS}
    if len(winners) == 1:
        attempt, questions = winners[0]
        return (
            row | _attempt_fields(client, attempt) | {"status": COMPLETED_STATUS, "clarification_questions": questions}
        )
    still_running = any(attempt.run.status not in TERMINAL_RUN_STATUSES for attempt in attempts)
    status = INCOMPLETE_STATUS if still_running else FAILED_STATUS
    return row | _attempt_fields(client, attempts[-1]) | {"status": status}


def reconstruct_batch(
    client: CanaryApiClient, *, dataset_name: str, revision: int, window: BatchWindow
) -> dict[str, Any]:
    snapshot = client.load_dataset_snapshot(dataset_name, revision)
    return {
        "run_id": window.batch_id,
        "dataset_revision": snapshot.revision,
        "cases": [reconstruct_case(client, case, window) for case in snapshot.cases],
    }


def score_case(case: dict[str, Any], raw_log: str) -> dict[str, Any]:
    routing = case.get("expected_routing") or ""
    status = case.get("status")
    row: dict[str, Any] = {
        "case_id": case.get("case_id"),
        "category": case.get("category"),
        "expected_metric": case.get("expected_metric"),
        "expected_routing": routing,
        "status": status,
        "task_id": case.get("task_id"),
        "task_run_id": case.get("task_run_id"),
        "task_url": case.get("task_url"),
        "clarification_questions": case.get("clarification_questions") or [],
    }
    if status != COMPLETED_STATUS:
        return row | {"verdict": UNSCORED_VERDICT, "reason": f"case status is {status}, not {COMPLETED_STATUS}"}
    try:
        expectations = expectations_for(routing, case.get("expected_metric"))
    except UnknownRouting as error:
        return row | {"verdict": UNSCORED_VERDICT, "reason": f"unrecognized expected_routing: {error}"}

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


def score_results(
    client: CanaryApiClient, results: dict[str, Any], case_ids: Sequence[str] = ()
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in results["cases"]:
        if case_ids and case["case_id"] not in case_ids:
            continue
        task_id, run_id = case.get("task_id"), case.get("task_run_id")
        scorable = case.get("status") == COMPLETED_STATUS and task_id and run_id
        raw_log = client.read_full_log(task_id, run_id) if scorable else ""
        rows.append(score_case(case, raw_log))
    return rows


def evaluation_event(*, run_id: str, dataset_revision: int | None, row: dict[str, Any]) -> dict[str, Any]:
    scored = row["verdict"] != UNSCORED_VERDICT
    properties: dict[str, Any] = {
        "$ai_experiment_id": run_id,
        "$ai_experiment_name": EXPERIMENT_NAME,
        "$ai_experiment_item_id": f"{run_id}:{row['case_id']}",
        "$ai_experiment_item_name": row["case_id"],
        "$ai_metric_name": EVALUATION_METRIC_NAME,
        "$ai_metric_version": "1",
        "$ai_status": "completed",
        "$ai_result_type": "boolean",
        "$ai_expected": row["expected_routing"],
        "$ai_evaluation_applicable": scored,
        "$ai_reasoning": (
            json.dumps({"failed": row["failed_checks"], "advisory": row["advisory_checks"]})
            if scored
            else row["reason"]
        ),
        "batch_id": run_id,
        "case_status": row["status"],
        "category": row["category"],
        "dataset_revision": dataset_revision,
        "task_id": row["task_id"],
        "task_run_id": row["task_run_id"],
        "task_url": row["task_url"],
    }
    if scored:
        properties |= {"$ai_score": 1 if row["verdict"] == "pass" else 0, "$ai_score_min": 0, "$ai_score_max": 1}
    return {
        "event": "$ai_evaluation",
        "distinct_id": f"{EXPERIMENT_NAME}:{run_id}",
        "properties": properties,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def emit_evaluation_event(*, host: str, capture_token: str, event: dict[str, Any]) -> None:
    response = httpx.post(
        f"{host.replace('us.posthog.com', 'us.i.posthog.com').rstrip('/')}/i/v0/e/",
        json=event | {"api_key": capture_token},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def summarize(run_id: str, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row["verdict"] != UNSCORED_VERDICT]
    passed = sum(row["verdict"] == "pass" for row in scored)
    unscored_by_status: dict[str, int] = {}
    for row in rows:
        if row["verdict"] == UNSCORED_VERDICT:
            unscored_by_status[str(row["status"])] = unscored_by_status.get(str(row["status"]), 0) + 1
    return {
        "run_id": run_id,
        "scored": len(scored),
        "passed": passed,
        "failed": len(scored) - passed,
        "unscored": len(rows) - len(scored),
        "unscored_by_status": unscored_by_status,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--results", help="Runner result JSON, or - for stdin")
    source.add_argument(
        "--batch",
        nargs=2,
        metavar=("FROM", "TO"),
        help="Rebuild the batch from tasks created in this ISO-8601 window instead of a results file",
    )
    parser.add_argument("--revision", type=int, help="Dataset revision to score against; required with --batch")
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--project-id", type=int, default=DEFAULT_PROJECT_ID)
    parser.add_argument("--case-id", action="append", dest="case_ids", default=[])
    parser.add_argument("--emit", action="store_true", help="Publish an $ai_evaluation event per case")
    args = parser.parse_args(argv)
    if args.batch and args.revision is None:
        parser.error("--batch requires --revision")
    return args


def _load_results(args: argparse.Namespace, client: CanaryApiClient) -> dict[str, Any]:
    if args.batch:
        window = BatchWindow(start=parse_batch_moment(args.batch[0]), end=parse_batch_moment(args.batch[1]))
        return reconstruct_batch(client, dataset_name=args.dataset_name, revision=args.revision, window=window)
    raw_results = sys.stdin.read() if args.results == "-" else open(args.results).read()
    return json.loads(raw_results)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    api_key = os.environ.get("POSTHOG_API_KEY")
    if not api_key:
        print("POSTHOG_API_KEY is required", file=sys.stderr)
        return 2
    capture_token = os.environ.get("POSTHOG_CAPTURE_TOKEN")
    if args.emit and not capture_token:
        print("POSTHOG_CAPTURE_TOKEN is required with --emit", file=sys.stderr)
        return 2

    with CanaryApiClient(host=args.host, project_id=args.project_id, api_key=api_key) as client:
        results = _load_results(args, client)
        rows = score_results(client, results, args.case_ids)

    run_id = results["run_id"]
    for row in rows:
        print(json.dumps(row))
        if args.emit and capture_token:
            event = evaluation_event(run_id=run_id, dataset_revision=results.get("dataset_revision"), row=row)
            emit_evaluation_event(host=args.host, capture_token=capture_token, event=event)
    print(json.dumps(summarize(run_id, rows)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
