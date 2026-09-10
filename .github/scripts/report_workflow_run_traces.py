#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "opentelemetry-api~=1.27",
#   "opentelemetry-sdk~=1.27",
#   "opentelemetry-exporter-otlp-proto-http~=1.27",
# ]
# ///
"""Emit OTLP traces for completed master workflow runs.

Scans the Actions API for master runs that finished since the last successful
run of this reporter and emits one trace per (run_id, run_attempt), shaped:

    <workflow>                       (root, one trace per run attempt)
    ├── <job>
    │   ├── queued                   (created_at -> started_at)
    │   └── <step>
    └── ...

Covers every workflow, including ones with no telemetry of their own (container
builds, image pushes, deploys). Complements report_test_timings.py, which emits
per-test traces from JUnit XML under its own trace IDs — these are separate
traces, not a parent for those.

Jobs of a reusable workflow invoked with `uses:` surface in the *caller* run as
`caller-job / callee-job`, so they land as ordinary children of the caller's
root span; `ci.job.caller` / `ci.job.callee` recover the two levels.

The runs list only reports each run's latest attempt, so earlier attempts of a
re-run are not traced. The trace ID folds in run_attempt, so the attempts that
are traced never collide.

Exit status is the watermark's only feedback channel. A tick that traced everything
it found exits 0. A tick that lost anything exits non-zero, so GitHub records the
run as failed and the next tick re-covers the window: an errored scan, a run whose
jobs would not load, or a batch the endpoint rejected. Re-emitting is free, because
span IDs are deterministic and an overlapping window is idempotent. Nothing gates on
this workflow, so a red tick costs a notification rather than a blocked merge.
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import hashlib
import logging
import argparse
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger("report_workflow_run_traces")

DEFAULT_OTLP_ENDPOINT = "https://us.i.posthog.com/i/v1/traces"
DEFAULT_REPO = "PostHog/posthog"
SERVICE_NAME = "ci-workflows"
INSTRUMENTATION_NAME = "posthog-ci-workflow-runs"
INSTRUMENTATION_VERSION = "0.1.0"

# Workflow file whose own run history is the watermark.
SELF_WORKFLOW_FILE = "ci-master-run-traces.yml"
# Workflows that cover master from a cron instead of from every push, scanned on their
# `schedule` runs as well. ci-backend.yml runs only the per-commit checks on a master push
# and its full test matrices hourly, so a push-only scan drops the heaviest CI workload in
# the repo. Hand-synced with SCHEDULED_GATING_WORKFLOWS in ci-alerts-devex.yml, which reads
# the same lanes for alerting.
SCHEDULED_MASTER_WORKFLOWS = ("ci-backend.yml",)
DEFAULT_LOOKBACK_HOURS = 6.0
DEFAULT_MAX_RUNS = 200

API_ROOT = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 20
API_ATTEMPTS = 3
API_BACKOFF_SECONDS = 2.0

# A single Backend CI run is ~3.6k spans and a cron tick throttled to hourly batches
# several runs, so the SDK default queue (2048) would silently drop the tail.
SPAN_QUEUE_SIZE = 65536
# ~230 KB serialized at this size — well clear of capture-logs' 2 MiB body limit.
SPAN_BATCH_SIZE = 512

EXIT_OK = 0
# Anything the tick meant to trace and lost. Holds the watermark at the last clean tick.
EXIT_INCOMPLETE = 1

RUN_ERROR_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
JOB_ERROR_CONCLUSIONS = frozenset({"failure", "timed_out"})
STEP_ERROR_CONCLUSIONS = frozenset({"failure"})

# Each token receives an identical copy of the spans (trace and span IDs are
# deterministic) — transitional dual emission while CI telemetry moves projects.
TOKEN_ENV_VARS = ("POSTHOG_DEVEX_PROJECT_API_TOKEN", "POSTHOG_CI_TRACES_EXTRA_TOKEN")

# One trailing parenthesized group, e.g. `Django tests – Core (…) (6/19)`.
MATRIX_SUFFIX_RE = re.compile(r"\s*\([^()]*\)\s*$")
REUSABLE_SEPARATOR = " / "


@dataclass(frozen=True)
class Step:
    number: int
    name: str
    status: str
    conclusion: str
    start: datetime
    end: datetime

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass(frozen=True)
class Job:
    id: int
    name: str
    status: str
    conclusion: str
    url: str
    runner_name: str
    runner_group_name: str
    labels: tuple[str, ...]
    created: datetime
    start: datetime
    end: datetime
    steps: tuple[Step, ...]

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def queued_seconds(self) -> float:
        return (self.start - self.created).total_seconds()


@dataclass(frozen=True)
class WorkflowRun:
    id: int
    attempt: int
    name: str
    path: str
    workflow_id: int
    run_number: int
    event: str
    status: str
    conclusion: str
    display_title: str
    head_sha: str
    head_branch: str
    actor: str
    triggering_actor: str
    repository: str
    html_url: str
    created: datetime
    start: datetime
    end: datetime
    jobs: tuple[Job, ...] = ()
    dropped_jobs: int = 0

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def queued_seconds(self) -> float:
        return (self.start - self.created).total_seconds()

    @property
    def step_count(self) -> int:
        return sum(len(job.steps) for job in self.jobs)


@dataclass(frozen=True)
class Collection:
    """What this tick resolved, and whether it resolved everything it found."""

    runs: tuple[WorkflowRun, ...] = ()
    complete: bool = True


# ---------- GitHub API ----------


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def _api_get(path: str, token: str, *, opener: Any = None) -> Any:
    """GET a GitHub API path, retrying transient failures only.

    5xx and network errors are worth another attempt; 403 and 404 are not — with an
    already-empty rate-limit bucket a retry just spends more of it.
    """
    url = f"{API_ROOT}/{path.lstrip('/')}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
            "User-Agent": INSTRUMENTATION_NAME,
        },
    )
    do_open = opener or urllib.request.urlopen
    for attempt in range(1, API_ATTEMPTS + 1):
        try:
            with do_open(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == API_ATTEMPTS:
                raise ApiError(f"GET {url} failed with {error.code}", error.code) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt == API_ATTEMPTS:
                raise ApiError(f"GET {url} failed: {error}") from error
        time.sleep(API_BACKOFF_SECONDS * attempt)
    raise ApiError(f"GET {url} exhausted {API_ATTEMPTS} attempts")


def _paginate(path: str, token: str, key: str, *, opener: Any = None) -> list[dict]:
    """Collect `key` across pages, stopping on a short page or the page cap."""
    joiner = "&" if "?" in path else "?"
    items: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        payload = _api_get(f"{path}{joiner}per_page={PER_PAGE}&page={page}", token, opener=opener)
        batch = payload.get(key) or []
        items.extend(batch)
        if len(batch) < PER_PAGE:
            return items
    logger.warning("hit the %d-page cap on %s; collected %d %s", MAX_PAGES, path, len(items), key)
    return items


def watermark(repo: str, token: str, *, lookback_hours: float, now: datetime, opener: Any = None) -> datetime:
    """Low-water mark: when the previous successful reporter run started.

    Reading our own run history is the entire state mechanism — no cache, no
    committed file. Keying on the last *success* means a failed tick doesn't
    advance the mark, so the next one re-covers the gap.
    """
    floor = now - timedelta(hours=lookback_hours)
    try:
        payload = _api_get(
            f"repos/{repo}/actions/workflows/{SELF_WORKFLOW_FILE}/runs?status=success&per_page=2",
            token,
            opener=opener,
        )
    except ApiError as error:
        # 404 just means this workflow has never run — the expected first tick, and
        # every local invocation. Anything else is worth a traceback.
        if error.status == 404:
            logger.info("no run history for %s yet; scanning from %s", SELF_WORKFLOW_FILE, floor.isoformat())
        else:
            logger.exception("could not read this reporter's own run history; falling back to %s", floor.isoformat())
        return floor
    runs = payload.get("workflow_runs") or []
    # Entry one is this run when it is already marked successful; entry two is the
    # previous success. A tick still in progress isn't listed, so either can be it.
    for run in runs:
        started = parse_iso_utc(run.get("run_started_at") or run.get("created_at") or "")
        if started is not None and started < now:
            return max(started, floor)
    logger.info("no previous successful run; falling back to %s", floor.isoformat())
    return floor


def scan_runs(repo: str, token: str, since: datetime, *, opener: Any = None) -> list[dict]:
    """Completed master runs whose completion lands at or after `since`, newest first.

    One scan per trigger event, because the API filters on a single event at a time. The
    repo-wide scan covers push, and each workflow in SCHEDULED_MASTER_WORKFLOWS is scanned
    for its `schedule` runs by workflow file. A repo-wide schedule scan would instead pull in
    every unrelated cron in the repo, and the frequent ones would crowd real CI runs out of
    the --max-runs cap.

    The API can only filter on `created`, so widen the window by a day and narrow
    on `updated_at` — which for a completed run is when it finished.
    """
    created_floor = (since - timedelta(days=1)).date().isoformat()

    def query(event: str) -> str:
        return urllib.parse.urlencode(
            {
                "branch": "master",
                "event": event,
                "status": "completed",
                "exclude_pull_requests": "true",
                "created": f">={created_floor}",
            }
        )

    paths = [f"repos/{repo}/actions/runs?{query('push')}"]
    paths += [
        f"repos/{repo}/actions/workflows/{workflow_file}/runs?{query('schedule')}"
        for workflow_file in SCHEDULED_MASTER_WORKFLOWS
    ]
    fresh = []
    for path in paths:
        for run in _paginate(path, token, "workflow_runs", opener=opener):
            updated = parse_iso_utc(run.get("updated_at") or "")
            if updated is not None and updated >= since:
                fresh.append(run)
    # Merging two scans breaks the API's newest-first order, which the --max-runs cap relies
    # on to keep the freshest runs.
    fresh.sort(
        key=lambda run: parse_iso_utc(run.get("updated_at") or "") or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    return fresh


def fetch_jobs(repo: str, run_id: int, attempt: int, token: str, *, opener: Any = None) -> list[dict]:
    return _paginate(
        f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs",
        token,
        "jobs",
        opener=opener,
    )


def fetch_run(repo: str, run_id: int, token: str, *, attempt: int = 0, opener: Any = None) -> dict:
    """The run's metadata, for `attempt` when given and for the latest attempt otherwise.

    The attempt-agnostic path always describes the latest attempt, so pairing it with
    an older attempt's jobs puts `run_started_at` after every job end and collapses the
    root span to zero length.
    """
    path = f"repos/{repo}/actions/runs/{run_id}"
    if attempt:
        path = f"{path}/attempts/{attempt}"
    return _api_get(path, token, opener=opener)


# ---------- Parsing ----------


def parse_iso_utc(value: str) -> datetime | None:
    """Parse an ISO 8601 timestamp; treat a naive one as UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def clamp(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Guarantee end >= start. Skipped jobs really do report completion a second early."""
    return start, max(start, end)


def split_reusable_name(name: str) -> tuple[str, str]:
    """`caller-job / callee-job` -> (caller, callee); ('', '') when not a reusable job.

    Splits on the first separator only: the callee half can contain another one.
    """
    caller, separator, callee = name.partition(REUSABLE_SEPARATOR)
    if not separator:
        return "", ""
    return caller, callee


def job_group_name(name: str) -> str:
    """Job name with one trailing matrix group removed, so matrix legs aggregate.

    Best-effort: a job whose real name simply ends in parentheses loses them too.
    """
    stripped = MATRIX_SUFFIX_RE.sub("", name)
    return stripped or name


def parse_step(raw: Mapping[str, Any], window: tuple[datetime, datetime]) -> Step | None:
    start = parse_iso_utc(raw.get("started_at") or "")
    end = parse_iso_utc(raw.get("completed_at") or "")
    if start is None or end is None:
        return None
    job_start, job_end = window
    # Step timestamps are second-granularity, so they can overhang the job window.
    start = min(max(start, job_start), job_end)
    end = min(max(end, job_start), job_end)
    start, end = clamp(start, end)
    return Step(
        number=int(raw.get("number") or 0),
        name=str(raw.get("name") or ""),
        status=str(raw.get("status") or ""),
        conclusion=str(raw.get("conclusion") or ""),
        start=start,
        end=end,
    )


def parse_job(raw: Mapping[str, Any]) -> Job | None:
    """Build a Job, or None when it never ran to completion (queued on a cancelled run)."""
    created = parse_iso_utc(raw.get("created_at") or "")
    start = parse_iso_utc(raw.get("started_at") or "")
    end = parse_iso_utc(raw.get("completed_at") or "")
    if end is None:
        return None
    if start is None:
        start = created or end
    if created is None:
        created = start
    created = min(created, start)
    start, end = clamp(start, end)
    steps = [step for step in (parse_step(s, (start, end)) for s in raw.get("steps") or []) if step is not None]
    steps.sort(key=lambda step: step.number)
    return Job(
        id=int(raw.get("id") or 0),
        name=str(raw.get("name") or ""),
        status=str(raw.get("status") or ""),
        conclusion=str(raw.get("conclusion") or ""),
        url=str(raw.get("html_url") or ""),
        runner_name=str(raw.get("runner_name") or ""),
        runner_group_name=str(raw.get("runner_group_name") or ""),
        labels=tuple(str(label) for label in raw.get("labels") or []),
        created=created,
        start=start,
        end=end,
        steps=tuple(steps),
    )


def parse_run(raw: Mapping[str, Any], raw_jobs: list[dict]) -> WorkflowRun | None:
    created = parse_iso_utc(raw.get("created_at") or "")
    start = parse_iso_utc(raw.get("run_started_at") or "") or created
    if start is None:
        logger.warning("run %s has no usable start timestamp; skipping", raw.get("id"))
        return None
    if created is None:
        created = start
    created = min(created, start)

    jobs: list[Job] = []
    dropped = 0
    for raw_job in raw_jobs:
        job = parse_job(raw_job)
        if job is None:
            dropped += 1
            continue
        jobs.append(job)
    jobs.sort(key=lambda job: (job.start, job.id))

    end = max((job.end for job in jobs), default=None) or parse_iso_utc(raw.get("updated_at") or "") or start
    start, end = clamp(start, end)
    return WorkflowRun(
        id=int(raw.get("id") or 0),
        attempt=int(raw.get("run_attempt") or 1),
        name=str(raw.get("name") or ""),
        path=str(raw.get("path") or ""),
        workflow_id=int(raw.get("workflow_id") or 0),
        run_number=int(raw.get("run_number") or 0),
        event=str(raw.get("event") or ""),
        status=str(raw.get("status") or ""),
        conclusion=str(raw.get("conclusion") or ""),
        display_title=str(raw.get("display_title") or ""),
        head_sha=str(raw.get("head_sha") or ""),
        head_branch=str(raw.get("head_branch") or ""),
        actor=str((raw.get("actor") or {}).get("login") or ""),
        triggering_actor=str((raw.get("triggering_actor") or {}).get("login") or ""),
        repository=str((raw.get("repository") or {}).get("full_name") or ""),
        html_url=str(raw.get("html_url") or ""),
        created=created,
        start=start,
        end=end,
        jobs=tuple(jobs),
        dropped_jobs=dropped,
    )


# ---------- OTLP export ----------


def deterministic_trace_id(run_id: int, run_attempt: int) -> int:
    """One trace per run attempt. Distinct from report_test_timings.py's per-shard keys."""
    digest = hashlib.sha256(f"{run_id}:{run_attempt}:workflow-run".encode()).digest()
    return int.from_bytes(digest[:16], "big")  # OTLP trace IDs are 128-bit.


def deterministic_span_id(*parts: object) -> int:
    """Span IDs derived from run/job/step identity, so a repeat emit is byte-identical."""
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode()).digest()
    span_id = int.from_bytes(digest[:8], "big")
    return span_id or 1  # zero is reserved as the invalid span ID


class _FixedIdGenerator(IdGenerator):
    """Hands out pre-computed IDs so every span is reproducible across emits.

    `trace_id` and `next_span_id` are set immediately before each start_span call;
    the generator has no state of its own to get out of sync.
    """

    def __init__(self) -> None:
        self.trace_id = 0
        self.next_span_id = 1

    def generate_trace_id(self) -> int:
        return self.trace_id

    def generate_span_id(self) -> int:
        return self.next_span_id


def _to_ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def run_resource_attributes(run: WorkflowRun) -> dict[str, str | int]:
    """Resource attributes for the *traced* run.

    Everything comes off the run payload — never this reporter's own GITHUB_* env,
    which describes the cron tick rather than the run being traced.
    """
    attrs: dict[str, str | int] = {
        "service.name": SERVICE_NAME,
        "ci.workflow": run.name,
        "ci.workflow_path": run.path,
        "ci.workflow_id": run.workflow_id,
        "ci.run_id": run.id,
        "ci.run_number": run.run_number,
        "ci.run_attempt": run.attempt,
        "ci.sha": run.head_sha,
        "ci.ref": f"refs/heads/{run.head_branch}" if run.head_branch else "",
        "ci.ref_name": run.head_branch,
        "ci.branch": run.head_branch,
        "ci.actor": run.actor,
        "ci.triggering_actor": run.triggering_actor,
        "ci.repository": run.repository,
        "ci.event_name": run.event,
        "ci.run_url": run.html_url,
    }
    return {k: v for k, v in attrs.items() if v != "" and v != 0}


class ExportError(Exception):
    pass


class _FailureRecordingExporter(SpanExporter):
    """Surfaces a rejected batch, which the SDK only logs.

    Without this an hour of 403s from the ingest endpoint reads as a clean tick and
    the watermark walks past every trace it dropped.
    """

    def __init__(self, inner: SpanExporter) -> None:
        self.inner = inner
        self.failed = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        # A transport failure (read timeout, refused connection, repeated connection
        # error) raises out of the inner exporter rather than returning FAILURE, and
        # the SDK's batch processor swallows that on its worker thread. Record it before
        # re-raising so the watermark check still sees the loss and the SDK still logs it.
        try:
            result = self.inner.export(spans)
        except Exception:
            self.failed = True
            raise
        if result is not SpanExportResult.SUCCESS:
            self.failed = True
        return result

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self.inner.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self.inner.shutdown()


def emit_trace(run: WorkflowRun, endpoint: str, token: str, exporter: Any = None) -> int:
    """Emit the run's whole span tree over OTLP HTTP. Returns the span count."""
    id_generator = _FixedIdGenerator()
    provider = TracerProvider(
        resource=Resource.create(run_resource_attributes(run)),
        id_generator=id_generator,
    )
    if exporter is None:
        exporter = OTLPSpanExporter(endpoint=endpoint, headers={"Authorization": f"Bearer {token}"})
    recorder = _FailureRecordingExporter(exporter)
    provider.add_span_processor(
        BatchSpanProcessor(recorder, max_queue_size=SPAN_QUEUE_SIZE, max_export_batch_size=SPAN_BATCH_SIZE)
    )
    tracer = provider.get_tracer(INSTRUMENTATION_NAME, INSTRUMENTATION_VERSION)
    id_generator.trace_id = deterministic_trace_id(run.id, run.attempt)

    try:
        span_count = _emit_run_span(tracer, id_generator, run)
    finally:
        # Drains the queue, so a rejected batch is recorded by the time this returns.
        provider.shutdown()
    if recorder.failed:
        raise ExportError(f"OTLP endpoint rejected spans for run {run.id} attempt {run.attempt}")
    return span_count


def _emit_run_span(tracer: trace.Tracer, ids: _FixedIdGenerator, run: WorkflowRun) -> int:
    ids.next_span_id = deterministic_span_id(run.id, run.attempt, "run")
    root = tracer.start_span(run.name or run.path, start_time=_to_ns(run.start))
    failed = sum(1 for job in run.jobs if job.conclusion in JOB_ERROR_CONCLUSIONS)
    skipped = sum(1 for job in run.jobs if job.conclusion == "skipped")
    for key, value in (
        ("ci.workflow.status", run.status),
        ("ci.workflow.conclusion", run.conclusion),
        ("ci.workflow.display_title", run.display_title),
        ("ci.workflow.duration_seconds", run.duration_seconds),
        ("ci.workflow.queued_seconds", max(run.queued_seconds, 0.0)),
        ("ci.workflow.job_count", len(run.jobs)),
        ("ci.workflow.failed_job_count", failed),
        ("ci.workflow.skipped_job_count", skipped),
        ("ci.workflow.dropped_job_count", run.dropped_jobs),
        ("ci.workflow.step_count", run.step_count),
    ):
        root.set_attribute(key, value)
    # `cancelled` stays UNSET: master runs get cancelled by concurrency routinely, and
    # marking them Error would bury the runs that actually broke.
    if run.conclusion in RUN_ERROR_CONCLUSIONS:
        root.set_status(Status(StatusCode.ERROR))

    span_count = 1
    with trace.use_span(root, end_on_exit=False):
        for job in run.jobs:
            span_count += _emit_job_span(tracer, ids, run, job)
    root.end(end_time=_to_ns(run.end))
    return span_count


def _emit_job_span(tracer: trace.Tracer, ids: _FixedIdGenerator, run: WorkflowRun, job: Job) -> int:
    ids.next_span_id = deterministic_span_id(run.id, run.attempt, "job", job.id)
    span = tracer.start_span(job.name, start_time=_to_ns(job.start))
    for key, value in (
        ("ci.job.id", job.id),
        ("ci.job.name", job.name),
        ("ci.job.group_name", job_group_name(job.name)),
        ("ci.job.url", job.url),
        ("ci.job.status", job.status),
        ("ci.job.conclusion", job.conclusion),
        ("ci.job.duration_seconds", job.duration_seconds),
        ("ci.job.queued_seconds", max(job.queued_seconds, 0.0)),
        ("ci.job.runner_name", job.runner_name),
        ("ci.job.runner_group_name", job.runner_group_name),
        # Joined rather than a sequence, so it stays one queryable value downstream.
        ("ci.job.labels", ",".join(job.labels)),
        ("ci.job.step_count", len(job.steps)),
    ):
        if value != "":
            span.set_attribute(key, value)
    caller, callee = split_reusable_name(job.name)
    if caller:
        span.set_attribute("ci.job.caller", caller)
        span.set_attribute("ci.job.callee", callee)
    if job.conclusion in JOB_ERROR_CONCLUSIONS:
        span.set_status(Status(StatusCode.ERROR))

    span_count = 1
    with trace.use_span(span, end_on_exit=False):
        # Without its own span the wait collapses into the first step, hiding the
        # one thing a queue delay looks like in a waterfall.
        if job.queued_seconds > 0:
            ids.next_span_id = deterministic_span_id(run.id, run.attempt, "queued", job.id)
            queued = tracer.start_span("queued", start_time=_to_ns(job.created))
            queued.set_attribute("ci.job.queued_seconds", job.queued_seconds)
            queued.set_attribute("ci.job.id", job.id)
            queued.end(end_time=_to_ns(job.start))
            span_count += 1
        for step in job.steps:
            ids.next_span_id = deterministic_span_id(run.id, run.attempt, "step", job.id, step.number)
            step_span = tracer.start_span(step.name, start_time=_to_ns(step.start))
            step_span.set_attribute("ci.step.number", step.number)
            step_span.set_attribute("ci.step.name", step.name)
            step_span.set_attribute("ci.step.status", step.status)
            step_span.set_attribute("ci.step.conclusion", step.conclusion)
            step_span.set_attribute("ci.step.duration_seconds", step.duration_seconds)
            step_span.set_attribute("ci.job.id", job.id)
            step_span.set_attribute("ci.job.name", job.name)
            if step.conclusion in STEP_ERROR_CONCLUSIONS:
                step_span.set_status(Status(StatusCode.ERROR))
            step_span.end(end_time=_to_ns(step.end))
            span_count += 1
    span.end(end_time=_to_ns(job.end))
    return span_count


def format_span_tree(run: WorkflowRun) -> Iterator[str]:
    yield (
        f"{run.name} [run {run.id} attempt {run.attempt}] "
        f"{run.conclusion or run.status} {run.duration_seconds:.0f}s "
        f"({len(run.jobs)} jobs, {run.step_count} steps, {run.dropped_jobs} dropped)"
    )
    for job in run.jobs:
        yield f"  ├─ {job.name} [{job.conclusion or job.status}] {job.duration_seconds:.0f}s queued {job.queued_seconds:.0f}s"
        for step in job.steps:
            yield f"  │    ├─ {step.name} [{step.conclusion or step.status}] {step.duration_seconds:.0f}s"


# ---------- CLI ----------


def emission_tokens(env: Mapping[str, str]) -> list[str]:
    """Distinct project API tokens to emit to, in ``TOKEN_ENV_VARS`` order."""
    tokens = (env.get(var, "") for var in TOKEN_ENV_VARS)
    return list(dict.fromkeys(token for token in tokens if token))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    parser.add_argument("--since", default="", help="ISO 8601 watermark override, for a manual backfill")
    parser.add_argument(
        "--run-id",
        action="append",
        type=int,
        default=[],
        help="trace exactly these runs and skip the scan (repeatable)",
    )
    parser.add_argument("--run-attempt", type=int, default=0, help="attempt for --run-id; default is the run's latest")
    parser.add_argument("--lookback-hours", type=float, default=DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--max-runs", type=int, default=DEFAULT_MAX_RUNS)
    parser.add_argument(
        "--otlp-endpoint", default=os.environ.get("POSTHOG_OTLP_TRACES_ENDPOINT") or DEFAULT_OTLP_ENDPOINT
    )
    parser.add_argument("--dry-run", action="store_true", help="print the span tree without emitting")
    return parser.parse_args(argv)


def collect_runs(args: argparse.Namespace, token: str, now: datetime) -> Collection:
    """Resolve the target runs into fully parsed span trees."""
    if args.run_id:
        raw_runs = [fetch_run(args.repo, run_id, token, attempt=args.run_attempt) for run_id in args.run_id]
    else:
        if args.run_attempt:
            # The scan returns latest-attempt payloads only, so an attempt override there
            # would pair one attempt's jobs with another attempt's window.
            logger.warning("--run-attempt only applies with --run-id; ignoring it for the scan")
        since = parse_iso_utc(args.since) or watermark(args.repo, token, lookback_hours=args.lookback_hours, now=now)
        logger.info("scanning master runs completed since %s", since.isoformat())
        raw_runs = scan_runs(args.repo, token, since)
        if len(raw_runs) > args.max_runs:
            # Not an incomplete tick: holding the watermark here would re-scan the same
            # oversized window forever. Freshest runs win and the backlog's tail is lost.
            logger.warning("found %d runs; capping at %d newest", len(raw_runs), args.max_runs)
            raw_runs = raw_runs[: args.max_runs]

    runs = []
    complete = True
    for raw in raw_runs:
        run_id = int(raw.get("id") or 0)
        # Both fetch paths report the attempt their payload describes, so jobs, metadata
        # and the trace ID stay on one attempt.
        attempt = int(raw.get("run_attempt") or 1)
        try:
            raw_jobs = fetch_jobs(args.repo, run_id, attempt, token)
        except ApiError:
            logger.exception("could not fetch jobs for run %s attempt %s; skipping", run_id, attempt)
            complete = False
            continue
        if not raw_jobs:
            # Startup failures and very early cancellations report zero jobs. A bare root
            # span holds no job time to attribute, and an empty list from a transient API
            # fault would look the same as a run that genuinely had none, so it is skipped.
            # This is also why `startup_failure` in RUN_ERROR_CONCLUSIONS never fires here.
            logger.info("run %s attempt %s has no jobs; nothing to trace", run_id, attempt)
            continue
        run = parse_run(raw, raw_jobs)
        if run is not None:
            runs.append(run)
    return Collection(runs=tuple(runs), complete=complete)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])

    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        logger.error("GITHUB_TOKEN is not set; nothing was traced")
        return EXIT_INCOMPLETE

    try:
        collection = collect_runs(args, github_token, datetime.now(UTC))
    except Exception:
        logger.exception("failed to collect workflow runs")
        return EXIT_INCOMPLETE

    if not collection.runs:
        logger.info("no completed master runs to trace")
        return EXIT_OK if collection.complete else EXIT_INCOMPLETE

    if args.dry_run or os.environ.get("DRY_RUN") == "1":
        for run in collection.runs:
            for line in format_span_tree(run):
                logger.info("%s", line)
        return EXIT_OK if collection.complete else EXIT_INCOMPLETE

    tokens = emission_tokens(os.environ)
    if not tokens:
        logger.error("none of %s set; nothing was emitted", ", ".join(TOKEN_ENV_VARS))
        return EXIT_INCOMPLETE

    complete = collection.complete
    for token in tokens:
        emitted = 0
        for run in collection.runs:
            # Per-run isolation: one malformed run must not cost the rest of the batch.
            try:
                emitted += emit_trace(run, args.otlp_endpoint, token)
            except Exception:
                logger.exception("failed to emit trace for run %s attempt %s", run.id, run.attempt)
                complete = False
        logger.info("emitted %d spans across %d runs to %s", emitted, len(collection.runs), args.otlp_endpoint)

    return EXIT_OK if complete else EXIT_INCOMPLETE


if __name__ == "__main__":
    sys.exit(main())
