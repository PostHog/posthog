"""Tests for report_test_timings.py — the JUnit-XML-to-PostHog parser."""

from __future__ import annotations

import sys
import textwrap
import importlib.util
from pathlib import Path

import pytest

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
        ("junit-results-backend-core-29", ("Core", "29")),
        ("junit-results-backend-temporal-5", ("Temporal", "5")),
        ("junit-results-backend-compat-1", ("Compat", "1")),
        ("junit-results-backend-core-poe-12", ("CorePoe", "12")),
        ("junit-results-async-migrations", ("AsyncMigrations", None)),
    ],
)
def test_derive_segment_and_group(dir_name: str, expected: tuple[str, str | None]) -> None:
    assert report_test_timings.derive_segment_and_group(dir_name) == expected


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
    import defusedxml.ElementTree as ET

    outcome, attempts = report_test_timings.classify_testcase(ET.fromstring(xml_snippet))
    assert outcome == expected_outcome
    assert attempts == expected_attempts


def test_collect_testcases_end_to_end(tmp_path: Path) -> None:
    """First testcase per file gets is_first_in_file=True; rest are False."""
    artifact_dir = tmp_path / "junit-results-backend-core-7"
    artifact_dir.mkdir()
    (artifact_dir / "junit-core.xml").write_text(
        textwrap.dedent("""\
        <?xml version="1.0"?>
        <testsuites>
          <testsuite name="pytest">
            <testcase classname="pkg.test_a.TestA" name="test_first" time="120.5"/>
            <testcase classname="pkg.test_a.TestA" name="test_second" time="0.5"/>
            <testcase classname="pkg.test_a.TestA" name="test_skip" time="0.0">
              <skipped message="not relevant"/>
            </testcase>
          </testsuite>
        </testsuites>
        """)
    )

    events = report_test_timings.collect_testcases(tmp_path)

    assert len(events) == 3
    assert events[0].test_name == "test_first"
    assert events[0].is_first_in_file is True
    assert events[0].duration_seconds == 120.5
    assert events[0].shard_segment == "Core"
    assert events[0].shard_group == "7"
    assert events[1].is_first_in_file is False
    assert events[1].outcome == "passed"
    assert events[2].outcome == "skipped"
    assert events[2].junit_filename == "junit-core.xml"


def test_collect_testcases_skips_malformed_xml(tmp_path: Path) -> None:
    """A broken XML file logs a warning and is skipped, doesn't fail collection."""
    artifact_dir = tmp_path / "junit-results-backend-core-1"
    artifact_dir.mkdir()
    (artifact_dir / "junit-core.xml").write_text("<not-valid-xml")
    assert report_test_timings.collect_testcases(tmp_path) == []
