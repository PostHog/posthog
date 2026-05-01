#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["posthoganalytics~=7.13", "defusedxml~=0.7"]
# ///
"""Emit per-test execution events from Backend CI JUnit XML artifacts.

Reads a directory of `junit-results-*` artifacts (downloaded by the workflow)
and sends one `posthog-ci-test-timing` event per `<testcase>` to the PostHog
DevEx project.

This script must NEVER fail the workflow: any unexpected error is logged and
the process exits 0. The workflow job is also `continue-on-error: true` as a
second belt for setup and artifact-download failures.
"""

from __future__ import annotations

import os
import sys
import json
import logging
import argparse
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET  # XXE-safe stdlib drop-in
from posthoganalytics import Posthog

logger = logging.getLogger("report_test_timings")

EVENT_NAME = "posthog-ci-test-timing"
POSTHOG_HOST = "https://us.i.posthog.com"
EMIT_PROGRESS_EVERY = 5000


@dataclass(frozen=True)
class TestEvent:
    """One emitted event per pytest testcase. Field names become event properties."""

    test_nodeid: str
    test_module: str
    test_file: str
    test_classname: str
    test_name: str
    duration_seconds: float
    outcome: str  # passed | failed | error | skipped | rerun_passed
    attempts: int  # 1 + number of pytest-rerunfailures retries before final outcome
    shard_segment: str  # e.g. Core, Temporal, Compat, AsyncMigrations
    shard_group: int | None  # e.g. 29 for shard 29 of N; None for unsharded jobs
    shard_total: int | None  # e.g. 38 for shard N of 38; None for unsharded jobs
    junit_filename: str
    is_first_in_file: bool  # the first testcase per file absorbs Django DB setup overhead


@dataclass(frozen=True)
class ArtifactInfo:
    path: Path
    segment: str
    group: int | None
    total: int | None


def derive_segment_and_group(artifact_dir_name: str) -> tuple[str, int | None]:
    """Parse `junit-results-backend-core-29` → ("Core", 29).

    Trailing numeric token is the shard group; the rest becomes a TitleCase
    segment. `junit-results-async-migrations` → ("AsyncMigrations", None).
    """
    suffix = artifact_dir_name.removeprefix("junit-results-backend-").removeprefix("junit-results-")
    parts = suffix.split("-")
    if len(parts) > 1 and parts[-1].isdigit():
        return "".join(p.title() for p in parts[:-1]), int(parts[-1])
    return "".join(p.title() for p in parts), None


def collect_artifact_infos(artifacts_root: Path) -> list[ArtifactInfo]:
    artifact_dirs = sorted(d for d in artifacts_root.iterdir() if d.is_dir()) or [artifacts_root]
    parsed_artifacts = [(artifact_dir, *derive_segment_and_group(artifact_dir.name)) for artifact_dir in artifact_dirs]

    groups_by_segment: dict[str, set[int]] = {}
    for _, segment, group in parsed_artifacts:
        if group is not None:
            groups_by_segment.setdefault(segment, set()).add(group)

    shard_totals = {
        segment: max(groups) if groups == set(range(1, max(groups) + 1)) else None
        for segment, groups in groups_by_segment.items()
    }

    return [
        ArtifactInfo(path=artifact_dir, segment=segment, group=group, total=shard_totals.get(segment))
        for artifact_dir, segment, group in parsed_artifacts
    ]


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


def derive_test_module_and_file(classname: str) -> tuple[str, str]:
    """Return a best-effort pytest module and file path from JUnit classname."""
    if not classname:
        return "", ""

    parts = classname.split(".")
    last_part = parts[-1]
    module_parts = parts[:-1] if len(parts) > 1 and last_part[:1].isupper() else parts
    module = ".".join(module_parts)
    test_file = f"{'/'.join(module_parts)}.py" if module_parts else ""
    return module, test_file


def iter_testcases(xml_path: Path) -> Iterator[Any]:
    """Yield `<testcase>` elements from a junit XML file. Tolerant of malformed input."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        logger.warning("failed to parse %s: %s", xml_path, exc)
        return
    root = tree.getroot()
    yield from root.iter("testcase")


def collect_testcases(artifacts_root: Path) -> list[TestEvent]:
    """Walk `artifacts_root`, return one `TestEvent` per JUnit `<testcase>`."""
    events: list[TestEvent] = []
    for artifact in collect_artifact_infos(artifacts_root):
        for xml_path in sorted(artifact.path.rglob("junit*.xml")):
            seen_files: set[str] = set()
            for tc in iter_testcases(xml_path):
                classname = tc.get("classname", "")
                name = tc.get("name", "")
                test_module, test_file = derive_test_module_and_file(classname)
                test_file = tc.get("file", "") or test_file
                outcome, attempts = classify_testcase(tc)
                try:
                    duration = float(tc.get("time", "0"))
                except ValueError:
                    duration = 0.0
                # First testcase per file absorbs Django DB setup (60-540s);
                # consumers should filter `is_first_in_file = false` for real timings.
                first_key = test_file or classname or name
                is_first = first_key not in seen_files
                seen_files.add(first_key)

                events.append(
                    TestEvent(
                        test_nodeid=to_nodeid(classname, name),
                        test_module=test_module,
                        test_file=test_file,
                        test_classname=classname,
                        test_name=name,
                        duration_seconds=duration,
                        outcome=outcome,
                        attempts=attempts,
                        shard_segment=artifact.segment,
                        shard_group=artifact.group,
                        shard_total=artifact.total,
                        junit_filename=xml_path.name,
                        is_first_in_file=is_first,
                    )
                )
    return events


def get_pull_request_number() -> int | None:
    """Read the PR number from the event payload, falling back to refs/pull/N."""
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
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not repository or not run_id:
        return ""
    return "{server_url}/{repository}/actions/runs/{run_id}".format(
        server_url=os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
        repository=repository,
        run_id=run_id,
    )


def workflow_context() -> dict[str, str | int | None]:
    """GitHub Actions context that decorates every emitted event."""
    keys = ("WORKFLOW", "RUN_ID", "RUN_NUMBER", "RUN_ATTEMPT", "REF", "SHA", "ACTOR", "REPOSITORY")
    context: dict[str, str | int | None] = {k.lower(): os.environ.get(f"GITHUB_{k}", "") for k in keys}
    context.update(
        {
            "event_name": os.environ.get("GITHUB_EVENT_NAME", ""),
            "head_ref": os.environ.get("GITHUB_HEAD_REF", ""),
            "base_ref": os.environ.get("GITHUB_BASE_REF", ""),
            "pr_number": get_pull_request_number(),
            "run_url": get_run_url(),
        }
    )
    return context


def emit(events: list[TestEvent], token: str) -> None:
    """Capture all events to PostHog DevEx and flush before returning.

    Without `shutdown()` the SDK's background consumer thread can be killed
    mid-flush when the process exits, dropping queued events.
    """
    client = Posthog(project_api_key=token, host=POSTHOG_HOST)
    distinct_id = f"ci-{os.environ.get('GITHUB_RUN_ID', 'local')}"
    context = workflow_context()
    try:
        for i, event in enumerate(events, start=1):
            client.capture(distinct_id=distinct_id, event=EVENT_NAME, properties={**context, **asdict(event)})
            if i % EMIT_PROGRESS_EVERY == 0:
                logger.info("queued %d / %d events", i, len(events))
    finally:
        client.shutdown()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("artifacts_root", type=Path, help="directory of downloaded junit-results-* artifacts")
    parser.add_argument("--dry-run", action="store_true", help="parse and summarize, do not emit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not args.artifacts_root.exists():
        logger.error("artifacts_root does not exist: %s", args.artifacts_root)
        return 0

    try:
        events = collect_testcases(args.artifacts_root)
    except Exception:
        logger.exception("failed to collect events")
        return 0

    logger.info("collected %d test events from %s", len(events), args.artifacts_root)
    if not events:
        return 0

    if args.dry_run or os.environ.get("DRY_RUN") == "1":
        for event in events[:5]:
            logger.info("  %-14s %7.2fs  %s", event.outcome, event.duration_seconds, event.test_nodeid)
        if len(events) > 5:
            logger.info("  ... and %d more", len(events) - 5)
        return 0

    token = os.environ.get("POSTHOG_DEVEX_PROJECT_API_TOKEN", "")
    if not token:
        logger.warning("POSTHOG_DEVEX_PROJECT_API_TOKEN not set; skipping emit")
        return 0

    try:
        emit(events, token)
        logger.info("emitted %d events to %s", len(events), POSTHOG_HOST)
    except Exception:
        logger.exception("failed to emit events")

    return 0


if __name__ == "__main__":
    sys.exit(main())
