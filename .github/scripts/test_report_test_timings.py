from __future__ import annotations

import sys
import json
import textwrap
import importlib.util
from pathlib import Path

import pytest

import defusedxml.ElementTree as ET

SCRIPT_PATH = Path(__file__).with_name("report_test_timings.py")
SPEC = importlib.util.spec_from_file_location("report_test_timings", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
report_test_timings = importlib.util.module_from_spec(SPEC)
# Register the module before exec so @dataclass can resolve the module via sys.modules.
sys.modules["report_test_timings"] = report_test_timings
SPEC.loader.exec_module(report_test_timings)


@pytest.mark.parametrize(
    "dir_name,expected",
    [
        ("junit-results-backend-core-29", ("backend", "core", 29)),
        ("junit-results-backend-temporal-5", ("backend", "temporal", 5)),
        ("junit-results-backend-compat-1", ("backend", "compat", 1)),
        ("junit-results-backend-core-poe-12", ("backend", "core-poe", 12)),
        ("junit-results-async-migrations", ("async-migrations", "async-migrations", None)),
        ("junit-results-dagster-3", ("dagster", "dagster", 3)),
        ("junit-results-llm-gateway", ("llm-gateway", "llm-gateway", None)),
    ],
)
def test_derive_suite_segment_and_group(dir_name: str, expected: tuple[str, str, int | None]) -> None:
    assert report_test_timings.derive_suite_segment_and_group(dir_name) == expected


@pytest.mark.parametrize(
    "classname,expected_module,expected_file",
    [
        (
            "posthog.hogql.test.test_resolver.TestResolver",
            "posthog.hogql.test.test_resolver",
            "posthog/hogql/test/test_resolver.py",
        ),
        (
            "posthog.hogql.test.test_resolver",
            "posthog.hogql.test.test_resolver",
            "posthog/hogql/test/test_resolver.py",
        ),
        ("", "", ""),
    ],
)
def test_derive_test_module_and_file(classname: str, expected_module: str, expected_file: str) -> None:
    assert report_test_timings.derive_test_module_and_file(classname) == (expected_module, expected_file)


@pytest.mark.parametrize(
    "classname,name,expected",
    [
        (
            "posthog.hogql.test.test_resolver.TestResolver",
            "test_x",
            "posthog/hogql/test/test_resolver/TestResolver::test_x",
        ),
        ("", "test_standalone", "test_standalone"),
        ("module", "test_y", "module::test_y"),
    ],
)
def test_to_nodeid(classname: str, name: str, expected: str) -> None:
    assert report_test_timings.to_nodeid(classname, name) == expected


@pytest.mark.parametrize(
    "xml_snippet,expected_outcome,expected_attempts",
    [
        ('<testcase classname="m" name="t" time="0.1"/>', "passed", 1),
        ('<testcase classname="m" name="t"><failure message="x"/></testcase>', "failed", 1),
        ('<testcase classname="m" name="t"><error message="x"/></testcase>', "error", 1),
        ('<testcase classname="m" name="t"><skipped message="x"/></testcase>', "skipped", 1),
        # pytest-rerunfailures: prior attempts as <rerunFailure> siblings, final attempt at end
        (
            '<testcase classname="m" name="t"><rerunFailure message="x"/><rerunFailure message="x"/></testcase>',
            "rerun_passed",
            3,
        ),
        (
            '<testcase classname="m" name="t"><rerunFailure message="x"/><failure message="x"/></testcase>',
            "failed",
            2,
        ),
    ],
)
def test_classify_testcase(xml_snippet: str, expected_outcome: str, expected_attempts: int) -> None:
    outcome, attempts = report_test_timings.classify_testcase(ET.fromstring(xml_snippet))
    assert outcome == expected_outcome
    assert attempts == expected_attempts


def test_collect_testcases_end_to_end(tmp_path: Path) -> None:
    for group in range(1, 7):
        (tmp_path / f"junit-results-backend-core-{group}").mkdir()
    artifact_dir = tmp_path / "junit-results-backend-core-7"
    artifact_dir.mkdir()
    (artifact_dir / "junit-core.xml").write_text(
        textwrap.dedent("""\
        <?xml version="1.0"?>
        <testsuites>
          <testsuite name="pytest">
            <testcase classname="pkg.test_a.TestA" name="test_first" time="120.5"/>
            <testcase classname="pkg.test_a.TestA" name="test_second" time="0.5"/>
            <testcase classname="pkg.test_a.TestB" name="test_other_class_same_file" time="0.7"/>
            <testcase classname="pkg.test_b.TestB" name="test_first_in_other_file" time="1.7"/>
            <testcase classname="pkg.test_a.TestA" name="test_skip" time="0.0">
              <skipped message="not relevant"/>
            </testcase>
          </testsuite>
        </testsuites>
        """)
    )

    events = report_test_timings.collect_testcases(tmp_path)

    assert len(events) == 5
    assert events[0].test_name == "test_first"
    assert events[0].test_module == "pkg.test_a"
    assert events[0].test_file == "pkg/test_a.py"
    assert events[0].is_first_in_file is True
    assert events[0].duration_seconds == 120.5
    assert events[0].test_suite == "backend"
    assert events[0].shard_segment == "core"
    assert events[0].shard_group == 7
    assert events[0].shard_total == 7
    assert events[1].is_first_in_file is False
    assert events[1].outcome == "passed"
    assert events[2].is_first_in_file is False
    assert events[3].test_file == "pkg/test_b.py"
    assert events[3].is_first_in_file is True
    assert events[4].outcome == "skipped"
    assert events[4].junit_filename == "junit-core.xml"


def test_collect_testcases_skips_malformed_xml(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "junit-results-backend-core-1"
    artifact_dir.mkdir()
    (artifact_dir / "junit-core.xml").write_text("<not-valid-xml")
    assert report_test_timings.collect_testcases(tmp_path) == []


def test_workflow_context_includes_query_and_drilldown_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"number": 57216}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_HEAD_REF", "worktree-per-test-telemetry-junit")
    monkeypatch.setenv("GITHUB_BASE_REF", "master")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "PostHog/posthog")
    monkeypatch.setenv("GITHUB_RUN_ID", "25218527467")

    context = report_test_timings.workflow_context()

    assert context["event_name"] == "pull_request"
    assert context["head_ref"] == "worktree-per-test-telemetry-junit"
    assert context["base_ref"] == "master"
    assert context["pr_number"] == 57216
    assert context["run_url"] == "https://github.com/PostHog/posthog/actions/runs/25218527467"
