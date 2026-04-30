#!/usr/bin/env python3
"""Emit per-test execution events from Backend CI JUnit XML artifacts.

Reads `junit-*.xml` files under the directory passed as argv[1] (typically a
folder of `junit-results-backend-*` artifacts downloaded by the workflow) and
sends one `posthog-ci-test-timing` event per `<testcase>` to the PostHog
DevEx project.

This script must NEVER fail the workflow: any unexpected error is logged and
the process exits 0. The workflow step is also `continue-on-error: true` as a
second belt.
"""

from __future__ import annotations

import os
import sys
import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

EVENT_NAME = "posthog-ci-test-timing"
POSTHOG_HOST = "https://us.i.posthog.com"


def parse_artifact_dir_name(dir_name: str) -> tuple[str, str | None]:
    """Derive (segment, group) from a junit-results-backend-* directory name.

    Examples:
      junit-results-backend-core-12 -> ("Core", "12")
      junit-results-backend-temporal-5 -> ("Temporal", "5")
      junit-results-backend-compat-2 -> ("Compat", "2")
      junit-results-async-migrations -> ("AsyncMigrations", None)
    """
    suffix = dir_name.removeprefix("junit-results-backend-").removeprefix("junit-results-")
    parts = suffix.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0].replace("-", "_").title().replace("_", ""), parts[1]
    return suffix.replace("-", "_").title().replace("_", ""), None


def classify_outcome(testcase: ET.Element) -> tuple[str, int]:
    """Return (outcome, attempts) from a <testcase> element.

    pytest-rerunfailures emits prior attempts as <rerunFailure>/<rerunError>
    children before the final outcome child. attempts = 1 + count(rerun*).
    """
    rerun_count = sum(1 for child in testcase if child.tag.startswith("rerun"))
    attempts = 1 + rerun_count
    for child in testcase:
        tag = child.tag
        if tag == "failure":
            return "failed", attempts
        if tag == "error":
            return "error", attempts
        if tag == "skipped":
            return "skipped", attempts
    return ("rerun_passed" if rerun_count else "passed"), attempts


def classname_to_nodeid(classname: str, name: str) -> str:
    """Convert pytest's JUnit classname.name into a nodeid-ish path.

    pytest writes classname as a dotted module path (optionally with class
    suffix), e.g. `posthog.hogql.test.test_resolver.TestResolver`. The
    canonical pytest nodeid uses `/` for the file path and `::` for the
    class/test separator; we approximate that since the JUnit format drops
    the `.py` and the file/class boundary.
    """
    if not classname:
        return name
    return f"{classname.replace('.', '/')}::{name}"


def iter_testcases(xml_path: Path) -> Iterable[ET.Element]:
    """Yield <testcase> elements from a junit XML file. Tolerant of malformed input."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        logger.warning("failed to parse %s: %s", xml_path, exc)
        return
    yield from tree.getroot().iter("testcase")


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


def collect_events(artifacts_root: Path) -> list[dict]:
    """Walk artifacts_root, return one event dict per testcase across all junit XML files."""
    base_props = {
        "workflow": env_str("GITHUB_WORKFLOW"),
        "runId": env_str("GITHUB_RUN_ID"),
        "runNumber": env_str("GITHUB_RUN_NUMBER"),
        "attempt": env_str("GITHUB_RUN_ATTEMPT"),
        "ref": env_str("GITHUB_REF"),
        "sha": env_str("GITHUB_SHA"),
        "actor": env_str("GITHUB_ACTOR"),
        "repository": env_str("GITHUB_REPOSITORY"),
        "emitted_at": datetime.now(UTC).isoformat(),
    }

    events: list[dict] = []
    artifact_dirs = sorted(d for d in artifacts_root.iterdir() if d.is_dir())
    if not artifact_dirs:
        artifact_dirs = [artifacts_root]

    for artifact_dir in artifact_dirs:
        segment, group = parse_artifact_dir_name(artifact_dir.name)
        xml_paths = sorted(artifact_dir.rglob("junit-*.xml")) + sorted(artifact_dir.rglob("junit.xml"))
        for xml_path in xml_paths:
            seen_files: set[str] = set()
            for tc in iter_testcases(xml_path):
                classname = tc.get("classname", "")
                name = tc.get("name", "")
                try:
                    duration = float(tc.get("time", "0"))
                except ValueError:
                    duration = 0.0
                outcome, attempts = classify_outcome(tc)
                # The first testcase per file absorbs Django DB setup overhead
                # (often 60-300s). Flag it so queries can filter it out.
                file_key = classname or name
                is_first = file_key not in seen_files
                seen_files.add(file_key)

                events.append(
                    {
                        **base_props,
                        "test_nodeid": classname_to_nodeid(classname, name),
                        "test_classname": classname,
                        "test_name": name,
                        "duration_seconds": duration,
                        "outcome": outcome,
                        "attempts": attempts,
                        "shard_segment": segment,
                        "shard_group": group,
                        "junit_filename": xml_path.name,
                        "is_first_in_file": is_first,
                    }
                )
    return events


def emit(events: list[dict], token: str) -> None:
    """Capture events to PostHog DevEx and shut down to flush the buffer."""
    from posthoganalytics import Posthog

    client = Posthog(project_api_key=token, host=POSTHOG_HOST)
    distinct_id = f"ci-{env_str('GITHUB_RUN_ID', 'local')}"
    for evt in events:
        client.capture(distinct_id=distinct_id, event=EVENT_NAME, properties=evt)
    # critical: flush the in-memory queue before process exit
    client.shutdown()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        logger.error("usage: report_test_timings.py <artifacts_root>")
        return 0

    artifacts_root = Path(sys.argv[1])
    if not artifacts_root.exists():
        logger.error("artifacts_root does not exist: %s", artifacts_root)
        return 0

    try:
        events = collect_events(artifacts_root)
    except Exception as exc:
        logger.exception("failed to collect events: %r", exc)
        return 0

    logger.info("collected %d test events from %s", len(events), artifacts_root)
    if not events:
        return 0

    if os.environ.get("DRY_RUN") == "1":
        for evt in events[:5]:
            logger.info("  %-14s %7.2fs  %s", evt["outcome"], evt["duration_seconds"], evt["test_nodeid"])
        if len(events) > 5:
            logger.info("  ... and %d more", len(events) - 5)
        return 0

    token = env_str("POSTHOG_DEVEX_PROJECT_API_TOKEN")
    if not token:
        logger.warning("POSTHOG_DEVEX_PROJECT_API_TOKEN not set; skipping emit")
        return 0

    try:
        emit(events, token)
        logger.info("emitted %d events to %s", len(events), POSTHOG_HOST)
    except Exception as exc:
        logger.exception("failed to emit events: %r", exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
