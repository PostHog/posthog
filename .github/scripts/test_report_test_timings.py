from __future__ import annotations

import sys
import json
import textwrap
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

import defusedxml.ElementTree as ET

SCRIPT_PATH = Path(__file__).with_name("report_test_timings.py")
SPEC = importlib.util.spec_from_file_location("report_test_timings", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
report_test_timings = importlib.util.module_from_spec(SPEC)
# Register before exec so @dataclass can resolve the module via sys.modules.
sys.modules["report_test_timings"] = report_test_timings
SPEC.loader.exec_module(report_test_timings)


# ---------- artifact name parsing ----------


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


# ---------- testcase classification ----------


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


# ---------- iso timestamp ----------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-05-04T15:23:45.123456", datetime(2026, 5, 4, 15, 23, 45, 123456, tzinfo=UTC)),
        ("2026-05-04T15:23:45+00:00", datetime(2026, 5, 4, 15, 23, 45, tzinfo=UTC)),
        ("2026-05-04T15:23:45-04:00", datetime(2026, 5, 4, 19, 23, 45, tzinfo=UTC)),
        ("", None),
        ("not-a-date", None),
    ],
)
def test_parse_iso_utc(value: str, expected: datetime | None) -> None:
    assert report_test_timings.parse_iso_utc(value) == expected


# ---------- shard parsing end-to-end ----------


def _write_shard_xml(artifact_dir: Path, *, filename: str, timestamp: str, time: str, body: str) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / filename).write_text(
        textwrap.dedent(
            f"""\
            <?xml version="1.0"?>
            <testsuites>
              <testsuite name="pytest" timestamp="{timestamp}" time="{time}">
                {body}
              </testsuite>
            </testsuites>
            """
        )
    )


def test_collect_shards_end_to_end(tmp_path: Path) -> None:
    for group in range(1, 7):
        (tmp_path / f"junit-results-backend-core-{group}").mkdir()
    _write_shard_xml(
        tmp_path / "junit-results-backend-core-7",
        filename="junit-core.xml",
        timestamp="2026-05-04T10:00:00.000000",
        time="123.5",
        body="""\
            <testcase classname="pkg.test_a.TestA" name="test_first" time="120.5"/>
            <testcase classname="pkg.test_a.TestA" name="test_second" time="0.5"/>
            <testcase classname="pkg.test_b.TestB" name="test_other_file" time="1.7"/>
            <testcase classname="pkg.test_a.TestA" name="test_skip" time="0.0">
              <skipped message="not relevant"/>
            </testcase>
        """,
    )

    shards = report_test_timings.collect_shards(tmp_path)

    assert len(shards) == 1
    shard = shards[0]
    assert shard.info.suite == "backend"
    assert shard.info.segment == "core"
    assert shard.info.group == 7
    assert shard.info.total == 7
    assert shard.start == datetime(2026, 5, 4, 10, 0, 0, tzinfo=UTC)
    assert (shard.end - shard.start).total_seconds() == pytest.approx(123.5)
    assert shard.junit_filename == "junit-core.xml"
    assert [t.name for t in shard.tests] == ["test_first", "test_second", "test_other_file", "test_skip"]
    assert shard.tests[0].duration_seconds == 120.5
    assert shard.tests[3].outcome == "skipped"


def test_collect_shards_skips_malformed_xml(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "junit-results-backend-core-1"
    artifact_dir.mkdir()
    (artifact_dir / "junit-core.xml").write_text("<not-valid-xml")
    assert report_test_timings.collect_shards(tmp_path) == []


def test_collect_shards_skips_missing_timestamp(tmp_path: Path) -> None:
    """Without `timestamp` we can't anchor spans on the timeline — skip the shard."""
    artifact_dir = tmp_path / "junit-results-backend-core-1"
    artifact_dir.mkdir()
    (artifact_dir / "junit-core.xml").write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" time="1.0"/></testsuites>'
    )
    assert report_test_timings.collect_shards(tmp_path) == []


# ---------- threshold filter ----------


@pytest.mark.parametrize(
    "outcome,attempts,duration,threshold,expected",
    [
        ("passed", 1, 0.1, 0.5, False),  # sub-threshold pass: dropped
        ("passed", 1, 0.5, 0.5, True),  # at threshold: kept
        ("passed", 1, 1.0, 0.5, True),  # above threshold: kept
        ("failed", 1, 0.0, 0.5, True),  # failure: kept regardless of duration
        ("error", 1, 0.0, 0.5, True),  # error: kept regardless of duration
        ("skipped", 1, 0.0, 0.5, False),  # sub-threshold skip: dropped
        ("rerun_passed", 3, 0.1, 0.5, True),  # rerun: kept regardless of duration
        ("passed", 2, 0.1, 0.5, True),  # any retry counts as signal
    ],
)
def test_should_emit(outcome: str, attempts: int, duration: float, threshold: float, expected: bool) -> None:
    test = report_test_timings.TestCase(
        nodeid="m::t",
        classname="m",
        name="t",
        duration_seconds=duration,
        outcome=outcome,
        attempts=attempts,
    )
    assert report_test_timings.should_emit(test, threshold) is expected


def test_filter_shards_preserves_shard_bounds_when_all_tests_dropped(tmp_path: Path) -> None:
    _write_shard_xml(
        tmp_path / "junit-results-backend-core-1",
        filename="junit-core.xml",
        timestamp="2026-05-04T10:00:00",
        time="60.0",
        body="""\
            <testcase classname="pkg.t.T" name="test_fast_a" time="0.1"/>
            <testcase classname="pkg.t.T" name="test_fast_b" time="0.2"/>
        """,
    )
    shards = report_test_timings.collect_shards(tmp_path)
    filtered = report_test_timings.filter_shards(shards, min_duration_seconds=0.5)
    assert len(filtered) == 1
    assert filtered[0].tests == []
    assert filtered[0].start == shards[0].start
    assert filtered[0].end == shards[0].end


def test_main_dry_run_reports_filter_summary(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write_shard_xml(
        tmp_path / "junit-results-backend-core-1",
        filename="junit-core.xml",
        timestamp="2026-05-04T10:00:00",
        time="61.0",
        body="""\
            <testcase classname="pkg.t.T" name="test_fast" time="0.1"/>
            <testcase classname="pkg.t.T" name="test_slow" time="60.0"/>
            <testcase classname="pkg.t.T" name="test_fail" time="0.0"><failure message="x"/></testcase>
        """,
    )
    with caplog.at_level("INFO", logger="report_test_timings"):
        rc = report_test_timings.main(["--dry-run", "--min-duration-seconds=0.5", str(tmp_path)])
    assert rc == 0
    summary = next(m for m in caplog.messages if "after" in m)
    assert "3 testcases (2 after 0.50s threshold filter)" in summary


# ---------- workflow context ----------


def test_workflow_resource_attributes_includes_query_and_drilldown_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"number": 57216}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_HEAD_REF", "worktree-per-test-telemetry-junit")
    monkeypatch.setenv("GITHUB_BASE_REF", "master")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "PostHog/posthog")
    monkeypatch.setenv("GITHUB_RUN_ID", "25218527467")

    attrs = report_test_timings.workflow_resource_attributes()

    assert attrs["ci.event_name"] == "pull_request"
    assert attrs["ci.head_ref"] == "worktree-per-test-telemetry-junit"
    assert attrs["ci.base_ref"] == "master"
    assert attrs["ci.pr_number"] == 57216
    assert attrs["ci.run_url"] == "https://github.com/PostHog/posthog/actions/runs/25218527467"


# ---------- trace id ----------


def test_deterministic_trace_id_is_stable_across_processes() -> None:
    a = report_test_timings.deterministic_trace_id("25218527467", "1")
    b = report_test_timings.deterministic_trace_id("25218527467", "1")
    assert a == b
    # Different attempt -> different trace id (so reruns of the same workflow run id are isolated).
    assert report_test_timings.deterministic_trace_id("25218527467", "2") != a
    # Result fits in 128 bits.
    assert 0 <= a < 2**128
