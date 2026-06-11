#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "defusedxml~=0.7",
#   "opentelemetry-api~=1.27",
#   "opentelemetry-sdk~=1.27",
#   "opentelemetry-exporter-otlp-proto-http~=1.27",
# ]
# ///
"""Emit OTLP traces from Backend CI JUnit XML artifacts.

Reads `junit-results-*` artifacts (downloaded by the workflow) and emits one
trace per workflow run shaped:

    ci-backend (root)
    └── <segment>-<group>            (shard)
        ├── <pytest nodeid>          (test)
        └── ...

Trace ID is deterministic per (run_id, run_attempt) so each workflow attempt
gets its own trace. Failures and errors mark spans Status.ERROR.

This script must NEVER fail the workflow: any unexpected error is logged and
the process exits 0. The workflow job is also `continue-on-error: true` as a
second belt for setup and artifact-download failures.
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
import logging
import secrets
import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

logger = logging.getLogger("report_test_timings")

DEFAULT_OTLP_ENDPOINT = "https://us.i.posthog.com/i/v1/traces"
SERVICE_NAME = "ci-backend"
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
    outcome: str  # passed | failed | error | skipped | rerun_passed
    attempts: int  # 1 + number of pytest-rerunfailures retries before final outcome


@dataclass(frozen=True)
class ArtifactInfo:
    path: Path
    suite: str
    segment: str
    group: int | None
    total: int | None


@dataclass(frozen=True)
class Shard:
    info: ArtifactInfo
    junit_filename: str
    start: datetime
    end: datetime
    testcase_seconds: float
    overhead_seconds: float
    tests: list[TestCase]


# ---------- artifact directory parsing ----------


def split_artifact_name(name_parts: list[str]) -> tuple[str, str]:
    if not name_parts:
        return "", ""
    if name_parts[0] == "backend" and len(name_parts) > 1:
        return "backend", "-".join(name_parts[1:])
    return "-".join(name_parts), "-".join(name_parts)


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
    parsed = [(d, *derive_suite_segment_and_group(d.name)) for d in artifact_dirs]

    groups_by_shard_key: dict[tuple[str, str], set[int]] = {}
    for _, suite, segment, group in parsed:
        if group is not None:
            groups_by_shard_key.setdefault((suite, segment), set()).add(group)

    shard_totals = {
        key: max(groups) if groups == set(range(1, max(groups) + 1)) else None
        for key, groups in groups_by_shard_key.items()
    }

    return [
        ArtifactInfo(path=d, suite=suite, segment=segment, group=group, total=shard_totals.get((suite, segment)))
        for d, suite, segment, group in parsed
    ]


# ---------- junit parsing ----------


def classify_testcase(testcase: Any) -> tuple[str, int]:
    """Return (outcome, attempts) from a single `<testcase>` element.

    pytest-rerunfailures emits prior attempts as `<rerunFailure>` /
    `<rerunError>` siblings before the final outcome child. Walk children once.
    """
    rerun_count = 0
    final_outcome: str | None = None
    for child in testcase:
        tag = child.tag
        if tag.startswith("rerun"):
            rerun_count += 1
        elif tag in ("failure", "error", "skipped") and final_outcome is None:
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


def parse_iso_utc(value: str) -> datetime | None:
    """Parse an ISO 8601 timestamp (pytest emits naive); treat as UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def parse_shard(xml_path: Path, info: ArtifactInfo) -> Shard | None:
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

    tests: list[TestCase] = []
    cursor = start
    for tc in suite_elem.iter("testcase"):
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        outcome, attempts = classify_testcase(tc)
        try:
            duration = float(tc.get("time", "0"))
        except ValueError:
            duration = 0.0
        test_start = cursor
        test_end = cursor + timedelta(seconds=duration)
        cursor = test_end
        tests.append(
            TestCase(
                nodeid=to_nodeid(classname, name),
                classname=classname,
                name=name,
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
    )


def collect_shards(artifacts_root: Path) -> list[Shard]:
    shards: list[Shard] = []
    for artifact in collect_artifact_infos(artifacts_root):
        for xml_path in sorted(artifact.path.rglob("junit*.xml")):
            shard = parse_shard(xml_path, artifact)
            if shard is not None:
                shards.append(shard)
    return shards


# ---------- threshold filter ----------


def should_emit(test: TestCase, min_duration_seconds: float) -> bool:
    """Emit signal-bearing testcases: failures, errors, reruns, or above the duration threshold."""
    if test.outcome in ("failed", "error"):
        return True
    if test.attempts > 1:
        return True
    return test.duration_seconds >= min_duration_seconds


def filter_shards(shards: list[Shard], min_duration_seconds: float) -> list[Shard]:
    """Prune sub-threshold passing tests; preserve shard wall-time bounds and order."""
    return [
        Shard(
            info=s.info,
            junit_filename=s.junit_filename,
            start=s.start,
            end=s.end,
            testcase_seconds=s.testcase_seconds,
            overhead_seconds=s.overhead_seconds,
            tests=[t for t in s.tests if should_emit(t, min_duration_seconds)],
        )
        for s in shards
    ]


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
    pr_number = get_pull_request_number()
    if pr_number is not None:
        attrs["ci.pr_number"] = pr_number
    attrs["ci.run_url"] = get_run_url()
    return {k: v for k, v in attrs.items() if v != ""}


# ---------- OTLP export ----------


def deterministic_trace_id(run_id: str, run_attempt: str) -> int:
    """One trace ID per (run_id, run_attempt). Reruns of the same attempt collide intentionally."""
    digest = hashlib.sha256(f"{run_id}:{run_attempt}".encode()).digest()
    return int.from_bytes(digest[:16], "big")  # OTLP trace IDs are 128-bit (16 bytes).


class _FixedTraceIdGenerator(IdGenerator):
    """Force every span in the run to share a deterministic trace ID."""

    def __init__(self, trace_id: int) -> None:
        self._trace_id = trace_id

    def generate_trace_id(self) -> int:
        return self._trace_id

    def generate_span_id(self) -> int:
        span_id = secrets.randbits(64)
        while span_id == 0:
            span_id = secrets.randbits(64)
        return span_id


def _to_ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def emit_traces(shards: list[Shard], endpoint: str, token: str) -> None:
    """Build root → shard → test span hierarchy and ship via OTLP HTTP."""
    run_id = os.environ.get("GITHUB_RUN_ID", "0")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    trace_id = deterministic_trace_id(run_id, run_attempt)

    resource = Resource.create({"service.name": SERVICE_NAME, **workflow_resource_attributes()})
    provider = TracerProvider(resource=resource, id_generator=_FixedTraceIdGenerator(trace_id))
    exporter = OTLPSpanExporter(endpoint=endpoint, headers={"Authorization": f"Bearer {token}"})
    provider.add_span_processor(BatchSpanProcessor(exporter, max_export_batch_size=SPAN_BATCH_SIZE))
    tracer = provider.get_tracer(INSTRUMENTATION_NAME, INSTRUMENTATION_VERSION)

    if not shards:
        provider.shutdown()
        return

    root_start = min(s.start for s in shards)
    root_end = max(s.end for s in shards)
    root_span = tracer.start_span(SERVICE_NAME, start_time=_to_ns(root_start))
    root_has_error = False
    with trace.use_span(root_span, end_on_exit=False):
        for shard in shards:
            if _emit_shard_span(tracer, shard):
                root_has_error = True

    if root_has_error:
        root_span.set_status(Status(StatusCode.ERROR))
    root_span.end(end_time=_to_ns(root_end))
    provider.shutdown()


def _emit_shard_span(tracer: trace.Tracer, shard: Shard) -> bool:
    """Emit shard span and its test children. Returns True iff any child has Error."""
    info = shard.info
    shard_name = f"{info.segment}-{info.group}" if info.group is not None else info.segment
    shard_span = tracer.start_span(shard_name, start_time=_to_ns(shard.start))
    shard_span.set_attribute("shard.suite", info.suite)
    shard_span.set_attribute("shard.segment", info.segment)
    if info.group is not None:
        shard_span.set_attribute("shard.group", info.group)
    if info.total is not None:
        shard_span.set_attribute("shard.total", info.total)
    shard_span.set_attribute("shard.junit_filename", shard.junit_filename)
    shard_span.set_attribute("shard.testcase_seconds", shard.testcase_seconds)
    shard_span.set_attribute("shard.overhead_seconds", shard.overhead_seconds)

    has_error = False
    with trace.use_span(shard_span, end_on_exit=False):
        # Pytest runs serially within a shard (no `-n` flag — confirmed in pytest.ini),
        # so parse-time cumulative durations give non-overlapping per-test windows
        # that stay stable even after threshold filtering.
        for test in shard.tests:
            test_span = tracer.start_span(test.nodeid, start_time=_to_ns(test.start))
            test_span.set_attribute("test.outcome", test.outcome)
            test_span.set_attribute("test.attempts", test.attempts)
            test_span.set_attribute("test.classname", test.classname)
            test_span.set_attribute("test.name", test.name)
            if test.outcome in ("failed", "error"):
                test_span.set_status(Status(StatusCode.ERROR))
                has_error = True
            test_span.end(end_time=_to_ns(test.end))

    if has_error:
        shard_span.set_status(Status(StatusCode.ERROR))
    shard_span.end(end_time=_to_ns(shard.end))
    return has_error


# ---------- CLI ----------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("artifacts_root", type=Path, help="directory of downloaded junit-results-* artifacts")
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not args.artifacts_root.exists():
        logger.error("artifacts_root does not exist: %s", args.artifacts_root)
        return 0

    try:
        shards = collect_shards(args.artifacts_root)
    except Exception:
        logger.exception("failed to collect shards")
        return 0

    pre_filter = sum(len(s.tests) for s in shards)
    shards = filter_shards(shards, args.min_duration_seconds)
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

    token = os.environ.get("POSTHOG_DEVEX_PROJECT_API_TOKEN", "")
    if not token:
        logger.warning("POSTHOG_DEVEX_PROJECT_API_TOKEN not set; skipping emit")
        return 0

    try:
        emit_traces(shards, args.otlp_endpoint, token)
        logger.info("emitted %d testcase spans to %s", post_filter, args.otlp_endpoint)
    except Exception:
        logger.exception("failed to emit traces")

    return 0


if __name__ == "__main__":
    sys.exit(main())
