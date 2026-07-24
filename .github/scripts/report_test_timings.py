#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "defusedxml~=0.7",
#   "opentelemetry-api~=1.27",
#   "opentelemetry-sdk~=1.27",
#   "opentelemetry-exporter-otlp-proto-http~=1.27",
#   "posthog-owners",
# ]
#
# [tool.uv.sources]
# posthog-owners = { path = "../../tools/owners" }
# ///
"""Emit OTLP traces from CI JUnit XML artifacts.

Reads `junit-results-*` artifacts (downloaded by the workflow) and emits one
trace per job (shard) shaped:

    <workflow> / <job>               (root, one trace per job)
    ├── <pytest nodeid>              (test)
    └── ...

Trace ID is deterministic per (run_id, run_attempt, job) so each job in each
workflow attempt gets its own trace. Failures and errors mark spans
Status.ERROR.

On a re-run attempt (GITHUB_RUN_ATTEMPT > 1) only the artifacts that attempt
uploaded (suffixed `-attempt<N>` by the workflow) are emitted, so shards the
attempt did not re-execute are never re-reported under the new attempt. Passes
of tests that failed in an earlier attempt of the same job are kept regardless
of duration: one commit failing then passing is the same-commit recovery proof
the flaky-test queue (engineering_analytics) classifies on.

This script must NEVER fail the workflow: any unexpected error is logged and
the process exits 0. The workflow job is also `continue-on-error: true` as a
second belt for setup and artifact-download failures.
"""

from __future__ import annotations

import os
import re
import sys
import json
import hashlib
import logging
import secrets
import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET  # XXE-safe stdlib drop-in
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.trace import Status, StatusCode
from posthog_owners import OwnersResolver

logger = logging.getLogger("report_test_timings")

DEFAULT_OTLP_ENDPOINT = "https://us.i.posthog.com/i/v1/traces"
DEFAULT_SERVICE_NAME = "ci-backend"
OWNERSHIP_CATALOG_SERVICE_NAME = "ci-ownership-catalog"
OWNERSHIP_CATALOG_SPAN_NAME = "ownership.catalog"
SUPPORTED_FRAMEWORKS = ("pytest", "jest")
INSTRUMENTATION_NAME = "posthog-ci-test-timings"
INSTRUMENTATION_VERSION = "0.1.0"
# ~150 KB serialized at this size — well under capture-logs' 2 MiB body limit.
SPAN_BATCH_SIZE = 1000


@dataclass(frozen=True)
class TestCase:
    nodeid: str
    classname: str
    name: str
    duration_seconds: float
    start: datetime
    end: datetime
    outcome: str  # passed | failed | error | skipped | xfailed | rerun_passed
    attempts: int  # 1 + number of pytest-rerunfailures retries before final outcome
    file: str  # repo-relative test file from JUnit's `file`; '' when absent (external shards)
    selector: str  # runnable 'path/test.py::Class::test' from JUnit's `file`; '' when file is absent


@dataclass(frozen=True)
class ArtifactInfo:
    path: Path
    suite: str
    segment: str
    group: int | None
    total: int | None
    # Which workflow run attempt uploaded the artifact (from the `-attempt<N>` name suffix); 1
    # when unsuffixed, i.e. every artifact predating re-run-aware uploads.
    attempt: int = 1


@dataclass(frozen=True)
class Shard:
    info: ArtifactInfo
    junit_filename: str
    start: datetime
    end: datetime
    testcase_seconds: float
    overhead_seconds: float
    tests: list[TestCase]
    # Wall-clock seconds from `<testsuite timestamp>` to the first test's logstart, as
    # reported by the `posthog-junit-timings` pytest plugin. Captures the shared
    # pre-first-test overhead (imports, collection, session/package fixture setup) so
    # the trace exporter can emit it as its own span instead of letting it visually
    # collapse into the first test. Zero when the plugin didn't run (external shards).
    setup_seconds: float = 0.0


# ---------- artifact directory parsing ----------


def split_artifact_name(name_parts: list[str]) -> tuple[str, str]:
    if not name_parts:
        return "", ""
    if name_parts[0] == "backend" and len(name_parts) > 1:
        return "backend", "-".join(name_parts[1:])
    return "-".join(name_parts), "-".join(name_parts)


_ATTEMPT_SUFFIX = re.compile(r"-attempt(\d+)$")


def split_attempt_suffix(artifact_dir_name: str) -> tuple[str, int]:
    """`junit-results-backend-core-29-attempt2` → ("junit-results-backend-core-29", 2).

    Re-run shards upload under an attempt-suffixed name so attempt 1's artifact survives
    (a same-name upload in a later attempt silently supersedes the earlier artifact).
    """
    match = _ATTEMPT_SUFFIX.search(artifact_dir_name)
    if match is None:
        return artifact_dir_name, 1
    return artifact_dir_name[: match.start()], int(match.group(1))


def derive_suite_segment_and_group(artifact_dir_name: str) -> tuple[str, str, int | None]:
    """Parse `junit-results-backend-core-29` → ("backend", "core", 29).

    Trailing numeric token is the shard group. Slug values are kept as-is so
    span attributes match workflow artifact names.
    """
    suffix = artifact_dir_name.removeprefix("junit-results-")
    parts = suffix.split("-")
    group = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else None
    name_parts = parts[:-1] if group is not None else parts
    suite, segment = split_artifact_name(name_parts)
    return suite, segment, group


def collect_artifact_infos(artifacts_root: Path) -> list[ArtifactInfo]:
    artifact_dirs = sorted(d for d in artifacts_root.iterdir() if d.is_dir()) or [artifacts_root]
    parsed: list[tuple[Path, str, str, int | None, int]] = []
    for d in artifact_dirs:
        base_name, attempt = split_attempt_suffix(d.name)
        parsed.append((d, *derive_suite_segment_and_group(base_name), attempt))

    groups_by_shard_key: dict[tuple[str, str], set[int]] = {}
    for _, suite, segment, group, _attempt in parsed:
        if group is not None:
            groups_by_shard_key.setdefault((suite, segment), set()).add(group)

    shard_totals = {
        key: max(groups) if groups == set(range(1, max(groups) + 1)) else None
        for key, groups in groups_by_shard_key.items()
    }

    return [
        ArtifactInfo(
            path=d, suite=suite, segment=segment, group=group, total=shard_totals.get((suite, segment)), attempt=attempt
        )
        for d, suite, segment, group, attempt in parsed
    ]


# ---------- junit parsing ----------


def is_retry_attempt(tag: str) -> bool:
    return tag.startswith("rerun") or tag in ("flakyFailure", "flakyError")


def classify_testcase(testcase: Any) -> tuple[str, int]:
    """Return (outcome, attempts) from a single `<testcase>` element.

    pytest's junitxml records nothing for pytest-rerunfailures attempts (a
    rerun report is neither passed, failed, nor skipped), so the root
    conftest's `posthog-junit-timings` plugin surfaces the retry count as a
    `posthog.reruns` testcase property. `<rerunFailure>`/`<rerunError>`
    children from other junit producers are honored too. Walk children once.
    """
    rerun_count = 0
    final_outcome: str | None = None
    for child in testcase:
        tag = child.tag
        if tag == "properties":
            for prop in child.findall("property"):
                if prop.get("name") == "posthog.reruns":
                    try:
                        rerun_count += max(0, int(prop.get("value", "0")))
                    except ValueError:
                        pass
        elif is_retry_attempt(tag):
            rerun_count += 1
        elif tag in ("failure", "error", "skipped") and final_outcome is None:
            if tag == "skipped" and child.get("type") == "pytest.xfail":
                # Quarantined-but-still-failing tests (xfail strict=False) must stay
                # distinguishable from plain skips in the analytics data.
                final_outcome = "xfailed"
            else:
                final_outcome = "failed" if tag == "failure" else tag
    if final_outcome is None:
        final_outcome = "rerun_passed" if rerun_count else "passed"
    return final_outcome, 1 + rerun_count


def to_nodeid(classname: str, name: str) -> str:
    """`posthog.hogql.test.test_resolver.TestResolver`, `test_x` → `posthog/hogql/test/test_resolver/TestResolver::test_x`.

    JUnit drops the `.py` and the file/class boundary; this is a best-effort
    reconstruction that's stable for grouping in queries.
    """
    return f"{classname.replace('.', '/')}::{name}" if classname else name


def to_selector(file: str, classname: str, name: str) -> str:
    """Runnable pytest selector 'path/to/test_x.py::TestClass::test_y' from JUnit's `file` + `classname`.

    Unlike `to_nodeid`, JUnit's `file` gives the exact module boundary, so nothing is guessed: the
    class portion is `classname` with the file's module prefix stripped. Returns '' when JUnit omits
    `file` (external shards) or the shape is unexpected — consumers fall back to the nodeid.
    """
    if not file or not name:
        return ""
    module = file[:-3].replace("/", ".") if file.endswith(".py") else ""
    if not classname:
        return f"{file}::{name}"
    if module and classname.startswith(module):
        class_part = classname[len(module) :].lstrip(".")
        return f"{file}::{class_part}::{name}" if class_part else f"{file}::{name}"
    return ""


def parse_iso_utc(value: str) -> datetime | None:
    """Parse an ISO 8601 timestamp (pytest emits naive); treat as UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def parse_testsuite_properties(suite_elem: Any) -> dict[str, str]:
    """Extract `<properties><property name=.. value=../></properties>` from `<testsuite>`.

    Pytest writes these via `record_testsuite_property` /
    `xml.add_global_property`. Returns an empty dict when no `<properties>` block
    exists (e.g., external shards without the `posthog-junit-timings` plugin).
    """
    properties_elem = suite_elem.find("properties")
    if properties_elem is None:
        return {}
    result: dict[str, str] = {}
    for prop in properties_elem.findall("property"):
        name = prop.get("name")
        value = prop.get("value")
        if name and value is not None:
            result[name] = value
    return result


def normalize_jest_file(file: str, junit_cwd: str) -> str:
    """Resolve jest-junit's package-relative `file` to a repository-relative path."""
    normalized = file.replace("\\", "/")
    workspace = os.environ.get("GITHUB_WORKSPACE", "").replace("\\", "/").rstrip("/")
    if workspace and normalized.startswith(f"{workspace}/"):
        return normalized[len(workspace) + 1 :]
    if normalized.startswith("/"):
        return ""
    repository_path = os.path.normpath(f"{junit_cwd}/{normalized}" if junit_cwd else normalized).replace("\\", "/")
    return "" if repository_path == ".." or repository_path.startswith("../") else repository_path


def jest_identity(file: str, name: str) -> str:
    return f"{file}::{name}" if file and name else name or file


def parse_shard(
    xml_path: Path,
    info: ArtifactInfo,
    *,
    framework: str = "pytest",
    junit_cwd: str = "",
) -> Shard | None:
    """One Shard per junit XML file. Tolerant of malformed input."""
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        logger.warning("failed to parse %s: %s", xml_path, exc)
        return None

    suite_elem = root if root.tag == "testsuite" else root.find("testsuite")
    if suite_elem is None:
        return None

    start = parse_iso_utc(suite_elem.get("timestamp", ""))
    if start is None:
        return None
    try:
        wall_seconds = float(suite_elem.get("time", "0"))
    except ValueError:
        wall_seconds = 0.0

    properties = parse_testsuite_properties(suite_elem)
    try:
        setup_seconds = max(0.0, float(properties.get("posthog.setup_seconds", "0")))
    except ValueError:
        setup_seconds = 0.0
    # Clamp to wall time so a clock skew or malformed property can't push tests past `end`.
    setup_seconds = min(setup_seconds, wall_seconds)

    tests: list[TestCase] = []
    cursor = start + timedelta(seconds=setup_seconds)
    for tc in suite_elem.iter("testcase"):
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        file = tc.get("file", "")
        if framework == "jest":
            file = normalize_jest_file(file, junit_cwd)
            nodeid = selector = jest_identity(file, name)
        else:
            nodeid = to_nodeid(classname, name)
            selector = to_selector(file, classname, name)
        outcome, attempts = classify_testcase(tc)
        try:
            duration = float(tc.get("time", "0"))
        except ValueError:
            duration = 0.0
        for child in tc:
            if is_retry_attempt(child.tag):
                try:
                    duration += max(0.0, float(child.get("time", "0")))
                except ValueError:
                    pass
        test_start = cursor
        test_end = cursor + timedelta(seconds=duration)
        cursor = test_end
        tests.append(
            TestCase(
                nodeid=nodeid,
                classname=classname,
                name=name,
                file=file,
                selector=selector,
                duration_seconds=duration,
                start=test_start,
                end=test_end,
                outcome=outcome,
                attempts=attempts,
            )
        )

    end = start + timedelta(seconds=wall_seconds)
    testcase_seconds = sum(t.duration_seconds for t in tests)
    return Shard(
        info=info,
        junit_filename=xml_path.name,
        start=start,
        end=end,
        testcase_seconds=testcase_seconds,
        overhead_seconds=max(0.0, wall_seconds - testcase_seconds),
        tests=tests,
        setup_seconds=setup_seconds,
    )


def collect_shards(artifacts_root: Path, *, framework: str = "pytest", junit_cwd: str = "") -> list[Shard]:
    shards: list[Shard] = []
    for artifact in collect_artifact_infos(artifacts_root):
        for xml_path in sorted(artifact.path.rglob("junit*.xml")):
            shard = parse_shard(xml_path, artifact, framework=framework, junit_cwd=junit_cwd)
            if shard is not None:
                shards.append(shard)
    return shards


# ---------- threshold filter ----------


def should_emit(test: TestCase, min_duration_seconds: float, prior_failed: frozenset[str] = frozenset()) -> bool:
    """Emit signal-bearing testcases: failures, errors, xfails, reruns, or above the duration threshold.

    ``prior_failed`` (re-run attempts only) holds the nodeids that failed in an earlier attempt of
    the same job: their passes are the same-commit recovery proof and are kept however fast.
    """
    if test.outcome in ("failed", "error", "xfailed"):
        return True
    if test.attempts > 1:
        return True
    if test.outcome == "passed" and test.nodeid in prior_failed:
        return True
    return test.duration_seconds >= min_duration_seconds


def filter_shards(
    shards: list[Shard],
    min_duration_seconds: float,
    prior_failed_by_job: dict[str, frozenset[str]] | None = None,
) -> list[Shard]:
    """Prune sub-threshold passing tests; preserve shard wall-time bounds and order."""
    prior_failed_by_job = prior_failed_by_job or {}

    def kept_tests(shard: Shard) -> list[TestCase]:
        prior_failed = prior_failed_by_job.get(job_trace_key(shard.info), frozenset())
        return [t for t in shard.tests if should_emit(t, min_duration_seconds, prior_failed)]

    return [
        Shard(
            info=s.info,
            junit_filename=s.junit_filename,
            start=s.start,
            end=s.end,
            testcase_seconds=s.testcase_seconds,
            overhead_seconds=s.overhead_seconds,
            tests=kept_tests(s),
            setup_seconds=s.setup_seconds,
        )
        for s in shards
    ]


# ---------- re-run attempts ----------


def current_run_attempt() -> int:
    """The workflow run attempt this emit runs under; 1 outside CI or on malformed input."""
    try:
        return max(1, int(os.environ.get("GITHUB_RUN_ATTEMPT", "1") or "1"))
    except ValueError:
        return 1


# ci-backend.yml greps for this function name to decide whether the checked-out script may emit
# on a re-run attempt; keep the name in sync with that probe if it ever changes.
def partition_run_attempt(shards: list[Shard], run_attempt: int) -> tuple[list[Shard], dict[str, frozenset[str]]]:
    """Split parsed shards for a re-run attempt: the shards this attempt executed, plus the
    nodeids that failed in earlier attempts keyed by job.

    Emitting only the current attempt's shards keeps an attempt from re-reporting shards it
    never ran (each run attempt's resource attributes stamp every span it emits). The per-job
    keying scopes recovery proof to the same matrix leg: a pass in a different leg runs a
    different config and proves nothing about the failure.
    """
    current = [s for s in shards if s.info.attempt == run_attempt]
    prior_failed: dict[str, set[str]] = {}
    for shard in shards:
        if shard.info.attempt >= run_attempt:
            continue
        for test in shard.tests:
            if test.outcome in ("failed", "error"):
                prior_failed.setdefault(job_trace_key(shard.info), set()).add(test.nodeid)
    return current, {key: frozenset(nodeids) for key, nodeids in prior_failed.items()}


# ---------- workflow context ----------


def get_pull_request_number() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_path:
        try:
            payload = json.loads(Path(event_path).read_text())
        except (OSError, json.JSONDecodeError):
            payload = {}
        number = payload.get("number")
        if isinstance(number, int):
            return number
    ref_parts = os.environ.get("GITHUB_REF", "").split("/")
    if len(ref_parts) >= 3 and ref_parts[0] == "refs" and ref_parts[1] == "pull" and ref_parts[2].isdigit():
        return int(ref_parts[2])
    return None


def get_run_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not repo or not run_id:
        return ""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repo}/actions/runs/{run_id}"


def workflow_resource_attributes() -> dict[str, str | int]:
    """Resource attributes attached to every span — pre-aggregation context for the run."""
    keys = ("WORKFLOW", "RUN_ID", "RUN_NUMBER", "RUN_ATTEMPT", "REF", "SHA", "ACTOR", "REPOSITORY")
    attrs: dict[str, str | int] = {f"ci.{k.lower()}": os.environ.get(f"GITHUB_{k}", "") for k in keys}
    attrs["ci.event_name"] = os.environ.get("GITHUB_EVENT_NAME", "")
    attrs["ci.head_ref"] = os.environ.get("GITHUB_HEAD_REF", "")
    attrs["ci.base_ref"] = os.environ.get("GITHUB_BASE_REF", "")
    attrs["ci.ref_name"] = os.environ.get("GITHUB_REF_NAME", "")
    # Branch name regardless of event: PR source branch, else the pushed branch.
    attrs["ci.branch"] = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    pr_number = get_pull_request_number()
    if pr_number is not None:
        attrs["ci.pr_number"] = pr_number
    attrs["ci.run_url"] = get_run_url()
    return {k: v for k, v in attrs.items() if v != ""}


# ---------- OTLP export ----------


def deterministic_trace_id(run_id: str, run_attempt: str, job_key: str) -> int:
    """One trace ID per (run_id, run_attempt, job). Reruns of the same attempt collide intentionally."""
    digest = hashlib.sha256(f"{run_id}:{run_attempt}:{job_key}".encode()).digest()
    return int.from_bytes(digest[:16], "big")  # OTLP trace IDs are 128-bit (16 bytes).


class _FixedTraceIdGenerator(IdGenerator):
    """Force every span to share whatever trace ID is currently set.

    `trace_id` is mutated between jobs so each job's root span (and its inherited
    test children) lands in its own trace while sharing one provider/exporter.
    """

    def __init__(self, trace_id: int = 0) -> None:
        self.trace_id = trace_id

    def generate_trace_id(self) -> int:
        return self.trace_id

    def generate_span_id(self) -> int:
        span_id = secrets.randbits(64)
        while span_id == 0:
            span_id = secrets.randbits(64)
        return span_id


def _to_ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def job_trace_key(info: ArtifactInfo) -> str:
    """Stable per-job identity; folds into the trace ID so each job is its own trace."""
    return f"{info.suite}:{info.segment}:{info.group}"


def job_trace_name(workflow: str, info: ArtifactInfo) -> str:
    """Human trace name `<workflow> / <job>` derived from the artifact, e.g. `Backend CI / core (29)`."""
    job = f"{info.segment} ({info.group})" if info.group is not None else info.segment
    return f"{workflow} / {job}"


def owner_team_lookup() -> Callable[[str], str]:
    """Repo-relative test file -> primary owning team slug, '' when unowned.

    Resolution is capture-time on purpose: a test is attributed to whoever owned it when it
    ran. Ownership is best-effort next to the timings themselves, so every failure — a resolver
    that can't load (a base checkout predating `tools/owners`) or one file that won't resolve —
    degrades to no stamp, leaving those spans in the reader's `unowned` bucket rather than
    losing the emit.
    """
    try:
        resolver = OwnersResolver()
    except Exception:
        logger.exception("owners resolver unavailable; emitting spans without team attribution")
        return lambda _file: ""

    @cache
    def lookup(file: str) -> str:
        if not file:
            return ""
        try:
            resolution = resolver.resolve(file)
        except Exception:
            logger.exception("owners resolution failed for %s; emitting span without team attribution", file)
            return ""
        if resolution.status != "active" or not resolution.owners:
            return ""
        primary = resolution.owners[0]
        return "" if primary.startswith("@") else primary

    return lookup


def emit_traces(
    shards: list[Shard],
    endpoint: str,
    token: str,
    *,
    service_name: str = DEFAULT_SERVICE_NAME,
    framework: str = "pytest",
) -> None:
    """Emit one trace per job: a `<workflow> / <job>` root span with test children, shipped via OTLP HTTP."""
    run_id = os.environ.get("GITHUB_RUN_ID", "0")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    workflow = os.environ.get("GITHUB_WORKFLOW", "") or service_name

    id_generator = _FixedTraceIdGenerator()
    resource = Resource.create({"service.name": service_name, **workflow_resource_attributes()})
    provider = TracerProvider(resource=resource, id_generator=id_generator)
    exporter = OTLPSpanExporter(endpoint=endpoint, headers={"Authorization": f"Bearer {token}"})
    provider.add_span_processor(BatchSpanProcessor(exporter, max_export_batch_size=SPAN_BATCH_SIZE))
    tracer = provider.get_tracer(INSTRUMENTATION_NAME, INSTRUMENTATION_VERSION)

    if not shards:
        provider.shutdown()
        return

    owner_of = owner_team_lookup()
    for shard in shards:
        # Mutate the shared generator before each job so its root span (and the test
        # children that inherit the active parent's trace ID) form a distinct trace.
        id_generator.trace_id = deterministic_trace_id(run_id, run_attempt, job_trace_key(shard.info))
        _emit_shard_span(tracer, shard, job_trace_name(workflow, shard.info), owner_of, framework)

    provider.shutdown()


def emit_ownership_catalog(endpoint: str, token: str) -> None:
    """Emit one repository-scoped heartbeat containing the active primary team roster."""
    teams = OwnersResolver().active_primary_teams()
    resource = Resource.create({"service.name": OWNERSHIP_CATALOG_SERVICE_NAME, **workflow_resource_attributes()})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, headers={"Authorization": f"Bearer {token}"})
    provider.add_span_processor(BatchSpanProcessor(exporter, max_export_batch_size=SPAN_BATCH_SIZE))
    tracer = provider.get_tracer(INSTRUMENTATION_NAME, INSTRUMENTATION_VERSION)
    span = tracer.start_span(OWNERSHIP_CATALOG_SPAN_NAME)
    span.set_attribute("ownership.catalog_version", 1)
    span.set_attribute("ownership.primary_teams_json", json.dumps(teams, separators=(",", ":")))
    span.set_attribute("ownership.primary_team_count", len(teams))
    span.end()
    provider.shutdown()


def _emit_shard_span(
    tracer: trace.Tracer,
    shard: Shard,
    root_name: str,
    owner_of: Callable[[str], str],
    framework: str = "pytest",
) -> bool:
    """Emit the job's root span and its test children. Returns True iff any child has Error."""
    info = shard.info
    shard_span = tracer.start_span(root_name, start_time=_to_ns(shard.start))
    shard_span.set_attribute("shard.suite", info.suite)
    shard_span.set_attribute("shard.segment", info.segment)
    if info.group is not None:
        shard_span.set_attribute("shard.group", info.group)
    if info.total is not None:
        shard_span.set_attribute("shard.total", info.total)
    shard_span.set_attribute("shard.junit_filename", shard.junit_filename)
    shard_span.set_attribute("shard.testcase_seconds", shard.testcase_seconds)
    shard_span.set_attribute("shard.overhead_seconds", shard.overhead_seconds)
    shard_span.set_attribute("shard.setup_seconds", shard.setup_seconds)

    has_error = False
    with trace.use_span(shard_span, end_on_exit=False):
        # Surface the pre-first-test gap (imports, collection, session/package fixtures)
        # as its own span — without it, the cursor-based reconstruction would visually
        # collapse this overhead into the first test's window.
        if shard.setup_seconds > 0:
            setup_span = tracer.start_span("setup", start_time=_to_ns(shard.start))
            setup_span.set_attribute("shard.setup_seconds", shard.setup_seconds)
            setup_span.end(end_time=_to_ns(shard.start + timedelta(seconds=shard.setup_seconds)))

        # Pytest runs serially within a shard (no `-n` flag — confirmed in pytest.ini),
        # so parse-time cumulative durations give non-overlapping per-test windows
        # that stay stable even after threshold filtering.
        for test in shard.tests:
            test_span = tracer.start_span(test.nodeid, start_time=_to_ns(test.start))
            test_span.set_attribute("test.outcome", test.outcome)
            test_span.set_attribute("test.attempts", test.attempts)
            test_span.set_attribute("test.framework", framework)
            test_span.set_attribute("test.job_key", job_trace_key(info))
            test_span.set_attribute("test.classname", test.classname)
            test_span.set_attribute("test.name", test.name)
            if test.selector:
                test_span.set_attribute("test.selector", test.selector)
            owner_team = owner_of(test.file)
            if owner_team:
                test_span.set_attribute("test.owner_team", owner_team)
            if test.outcome in ("failed", "error"):
                test_span.set_status(Status(StatusCode.ERROR))
                has_error = True
            test_span.end(end_time=_to_ns(test.end))

    if has_error:
        shard_span.set_status(Status(StatusCode.ERROR))
    shard_span.end(end_time=_to_ns(shard.end))
    return has_error


# ---------- CLI ----------

# Each token receives an identical copy of the spans (trace IDs are deterministic) —
# transitional dual emission while CI telemetry moves projects.
TOKEN_ENV_VARS = ("POSTHOG_DEVEX_PROJECT_API_TOKEN", "POSTHOG_CI_TRACES_EXTRA_TOKEN")


def emission_tokens(env: Mapping[str, str]) -> list[str]:
    """Distinct project API tokens to emit to, in ``TOKEN_ENV_VARS`` order."""
    tokens = (env.get(var, "") for var in TOKEN_ENV_VARS)
    return list(dict.fromkeys(token for token in tokens if token))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "artifacts_root",
        type=Path,
        nargs="?",
        help="directory of downloaded junit-results-* artifacts",
    )
    parser.add_argument(
        "--framework",
        choices=SUPPORTED_FRAMEWORKS,
        default="pytest",
        help="JUnit producer to normalize (default: pytest)",
    )
    parser.add_argument(
        "--service-name",
        default=DEFAULT_SERVICE_NAME,
        help=f"OTel service.name for emitted spans (default: {DEFAULT_SERVICE_NAME})",
    )
    parser.add_argument(
        "--junit-cwd",
        default="",
        help="repository-relative working directory used by the JUnit producer",
    )
    parser.add_argument(
        "--min-duration-seconds",
        type=float,
        default=0.5,
        help="drop sub-threshold passing testcases (failures/reruns kept regardless)",
    )
    parser.add_argument(
        "--otlp-endpoint",
        default=os.environ.get("POSTHOG_OTLP_TRACES_ENDPOINT", DEFAULT_OTLP_ENDPOINT),
        help=f"OTLP /v1/traces endpoint (default: $POSTHOG_OTLP_TRACES_ENDPOINT or {DEFAULT_OTLP_ENDPOINT})",
    )
    parser.add_argument("--dry-run", action="store_true", help="parse and summarize, do not emit")
    parser.add_argument(
        "--emit-ownership-catalog",
        action="store_true",
        help="emit the repository ownership roster heartbeat instead of JUnit spans",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.emit_ownership_catalog:
        if args.dry_run or os.environ.get("DRY_RUN") == "1":
            logger.info("ownership catalog: %d active primary teams", len(OwnersResolver().active_primary_teams()))
            return 0
        tokens = emission_tokens(os.environ)
        if not tokens:
            logger.warning("none of %s set; skipping emit", ", ".join(TOKEN_ENV_VARS))
            return 0
        for token in tokens:
            try:
                emit_ownership_catalog(args.otlp_endpoint, token)
            except Exception:
                logger.exception("failed to emit ownership catalog")
        return 0

    if args.artifacts_root is None:
        logger.error("artifacts_root is required unless --emit-ownership-catalog is set")
        return 0
    if not args.artifacts_root.exists():
        logger.error("artifacts_root does not exist: %s", args.artifacts_root)
        return 0

    try:
        shards = collect_shards(args.artifacts_root, framework=args.framework, junit_cwd=args.junit_cwd)
    except Exception:
        logger.exception("failed to collect shards")
        return 0

    run_attempt = current_run_attempt()
    prior_failed_by_job: dict[str, frozenset[str]] = {}
    if run_attempt > 1:
        shards, prior_failed_by_job = partition_run_attempt(shards, run_attempt)
        logger.info(
            "re-run attempt %d: emitting %d re-executed shards (%d jobs carry earlier-attempt failures)",
            run_attempt,
            len(shards),
            len(prior_failed_by_job),
        )

    pre_filter = sum(len(s.tests) for s in shards)
    shards = filter_shards(shards, args.min_duration_seconds, prior_failed_by_job)
    post_filter = sum(len(s.tests) for s in shards)
    logger.info(
        "collected %d shards, %d testcases (%d after %.2fs threshold filter)",
        len(shards),
        pre_filter,
        post_filter,
        args.min_duration_seconds,
    )

    if not shards:
        return 0

    if args.dry_run or os.environ.get("DRY_RUN") == "1":
        for shard in shards[:3]:
            logger.info(
                "  %s/%s shard %s: %d tests, %.1fs wall",
                shard.info.suite,
                shard.info.segment,
                shard.info.group,
                len(shard.tests),
                (shard.end - shard.start).total_seconds(),
            )
        return 0

    tokens = emission_tokens(os.environ)
    if not tokens:
        logger.warning("none of %s set; skipping emit", ", ".join(TOKEN_ENV_VARS))
        return 0

    for token in tokens:
        # Per-token isolation: one project's ingest failing must not block the other's.
        try:
            emit_traces(
                shards,
                args.otlp_endpoint,
                token,
                service_name=args.service_name,
                framework=args.framework,
            )
            logger.info("emitted %d testcase spans to %s", post_filter, args.otlp_endpoint)
        except Exception:
            logger.exception("failed to emit traces")

    return 0


if __name__ == "__main__":
    sys.exit(main())
