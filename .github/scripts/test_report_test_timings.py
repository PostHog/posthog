from __future__ import annotations

import sys
import json
import textwrap
import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from defusedxml import ElementTree

SCRIPT_PATH = Path(__file__).with_name("report_test_timings.py")
SPEC = importlib.util.spec_from_file_location("report_test_timings", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
report_test_timings = importlib.util.module_from_spec(SPEC)
# Register before exec so @dataclass can resolve the module via sys.modules.
sys.modules["report_test_timings"] = report_test_timings
SPEC.loader.exec_module(report_test_timings)


def _testcase(
    *,
    outcome: str = "passed",
    attempts: int = 1,
    duration: float = 1.0,
    start: datetime | None = None,
    name: str = "t",
) -> report_test_timings.TestCase:  # type: ignore[name-defined]
    test_start = start if start is not None else datetime(2026, 5, 4, 10, 0, 0, tzinfo=UTC)
    return report_test_timings.TestCase(
        nodeid=f"m::{name}",
        classname="m",
        name=name,
        duration_seconds=duration,
        start=test_start,
        end=test_start + timedelta(seconds=duration),
        outcome=outcome,
        attempts=attempts,
    )


# ---------- artifact name parsing ----------


@pytest.mark.parametrize(
    "dir_name,expected",
    [
        ("junit-results-backend-core-29", ("backend", "core", 29)),
        ("junit-results-async-migrations", ("async-migrations", "async-migrations", None)),
        ("junit-results-llm-gateway", ("llm-gateway", "llm-gateway", None)),
    ],
)
def test_derive_suite_segment_and_group(dir_name: str, expected: tuple[str, str, int | None]) -> None:
    assert report_test_timings.derive_suite_segment_and_group(dir_name) == expected


# ---------- shard parsing end-to-end ----------


def _write_shard_xml(
    artifact_dir: Path,
    *,
    filename: str,
    timestamp: str,
    time: str,
    body: str,
    properties: dict[str, str] | None = None,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    properties_block = ""
    if properties:
        # Single line keeps `textwrap.dedent` below honest — an unindented inner line would zero the common prefix.
        property_elements = "".join(f'<property name="{n}" value="{v}"/>' for n, v in properties.items())
        properties_block = f"<properties>{property_elements}</properties>"
    (artifact_dir / filename).write_text(
        textwrap.dedent(
            f"""\
            <?xml version="1.0"?>
            <testsuites>
              <testsuite name="pytest" timestamp="{timestamp}" time="{time}">
                {properties_block}
                {body}
              </testsuite>
            </testsuites>
            """
        )
    )


def test_collect_shards_builds_test_windows_and_overhead(tmp_path: Path) -> None:
    for group in range(1, 7):
        (tmp_path / f"junit-results-backend-core-{group}").mkdir()
    _write_shard_xml(
        tmp_path / "junit-results-backend-core-7",
        filename="junit-core.xml",
        timestamp="2026-05-04T10:00:00.000000",
        time="10.0",
        body="""\
            <testcase classname="pkg.test_a.TestA" name="test_fast" time="0.1"/>
            <testcase classname="pkg.test_a.TestA" name="test_slow" time="2.0"/>
            <testcase classname="pkg.test_a.TestA" name="test_rerun" time="0.2">
              <rerunFailure message="x"/>
            </testcase>
            <testcase classname="pkg.test_a.TestA" name="test_fail" time="0.1"><failure message="x"/></testcase>
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
    assert (shard.end - shard.start).total_seconds() == pytest.approx(10.0)
    assert shard.testcase_seconds == pytest.approx(2.4)
    assert shard.overhead_seconds == pytest.approx(7.6)
    assert shard.junit_filename == "junit-core.xml"
    assert [t.name for t in shard.tests] == ["test_fast", "test_slow", "test_rerun", "test_fail"]
    assert shard.tests[0].nodeid == "pkg/test_a/TestA::test_fast"
    assert shard.tests[0].start == shard.start
    assert shard.tests[0].end == datetime(2026, 5, 4, 10, 0, 0, 100000, tzinfo=UTC)
    assert shard.tests[1].start == shard.tests[0].end
    assert shard.tests[2].start == datetime(2026, 5, 4, 10, 0, 2, 100000, tzinfo=UTC)
    assert shard.tests[2].outcome == "rerun_passed"
    assert shard.tests[2].attempts == 2
    assert shard.tests[3].outcome == "failed"


# ---------- rerun classification (posthog.reruns testcase property) ----------


@pytest.mark.parametrize(
    "testcase_xml,expected",
    [
        # pytest 8's junitxml drops rerun attempts entirely; the posthog-junit-timings
        # plugin records them as a testcase property — the only rerun signal we get.
        (
            '<testcase name="t"><properties><property name="posthog.reruns" value="2"/></properties></testcase>',
            ("rerun_passed", 3),
        ),
        # A rerun count must not mask a test that exhausted its retries and failed.
        (
            '<testcase name="t"><properties><property name="posthog.reruns" value="2"/></properties>'
            '<failure message="x"/></testcase>',
            ("failed", 3),
        ),
        # Malformed value must never crash the exporter.
        (
            '<testcase name="t"><properties><property name="posthog.reruns" value="garbage"/></properties></testcase>',
            ("passed", 1),
        ),
    ],
)
def test_classify_testcase_reads_rerun_property(testcase_xml: str, expected: tuple[str, int]) -> None:
    assert report_test_timings.classify_testcase(ElementTree.fromstring(testcase_xml)) == expected


# ---------- setup_seconds (posthog-junit-timings plugin) ----------


def test_parse_shard_shifts_tests_past_setup_seconds(tmp_path: Path) -> None:
    _write_shard_xml(
        tmp_path / "junit-results-backend-core-1",
        filename="junit-core.xml",
        timestamp="2026-05-04T10:00:00",
        time="10.0",
        properties={"posthog.setup_seconds": "3.5", "posthog.collection_seconds": "0.4"},
        body="""\
            <testcase classname="pkg.t.T" name="test_a" time="1.0"/>
            <testcase classname="pkg.t.T" name="test_b" time="2.0"/>
        """,
    )

    shard = report_test_timings.collect_shards(tmp_path)[0]

    assert shard.setup_seconds == pytest.approx(3.5)
    # First test no longer starts at shard.start — it starts after the setup gap.
    assert shard.tests[0].start == datetime(2026, 5, 4, 10, 0, 3, 500000, tzinfo=UTC)
    assert shard.tests[0].end == datetime(2026, 5, 4, 10, 0, 4, 500000, tzinfo=UTC)
    assert shard.tests[1].start == shard.tests[0].end
    # Shard wall-clock bounds are unaffected by the property.
    assert (shard.end - shard.start).total_seconds() == pytest.approx(10.0)


def test_parse_shard_defaults_setup_to_zero_when_property_missing(tmp_path: Path) -> None:
    _write_shard_xml(
        tmp_path / "junit-results-backend-core-1",
        filename="junit-core.xml",
        timestamp="2026-05-04T10:00:00",
        time="5.0",
        body='<testcase classname="pkg.t.T" name="test_a" time="1.0"/>',
    )

    shard = report_test_timings.collect_shards(tmp_path)[0]

    assert shard.setup_seconds == 0.0
    assert shard.tests[0].start == shard.start


@pytest.mark.parametrize(
    "raw_value,expected",
    [
        ("not-a-float", 0.0),  # malformed → fall back to zero, don't crash
        ("-1.5", 0.0),  # negative → clamp to zero
        ("999.0", 5.0),  # exceeds wall time → clamp to wall_seconds to avoid pushing tests past shard.end
    ],
)
def test_parse_shard_handles_malformed_or_out_of_range_setup_seconds(
    tmp_path: Path, raw_value: str, expected: float
) -> None:
    _write_shard_xml(
        tmp_path / "junit-results-backend-core-1",
        filename="junit-core.xml",
        timestamp="2026-05-04T10:00:00",
        time="5.0",
        properties={"posthog.setup_seconds": raw_value},
        body='<testcase classname="pkg.t.T" name="test_a" time="1.0"/>',
    )

    shard = report_test_timings.collect_shards(tmp_path)[0]

    assert shard.setup_seconds == pytest.approx(expected)


def test_parse_testsuite_properties_returns_empty_when_block_missing(tmp_path: Path) -> None:
    _write_shard_xml(
        tmp_path / "junit-results-backend-core-1",
        filename="junit-core.xml",
        timestamp="2026-05-04T10:00:00",
        time="1.0",
        body='<testcase classname="pkg.t.T" name="t" time="0.5"/>',
    )
    import defusedxml.ElementTree as ET

    suite = ET.parse(tmp_path / "junit-results-backend-core-1" / "junit-core.xml").getroot().find("testsuite")
    assert report_test_timings.parse_testsuite_properties(suite) == {}


# ---------- threshold filter ----------


@pytest.mark.parametrize(
    "outcome,attempts,duration,threshold,expected",
    [
        ("passed", 1, 0.1, 0.5, False),  # sub-threshold pass: dropped
        ("passed", 1, 1.0, 0.5, True),  # above threshold: kept
        ("failed", 1, 0.0, 0.5, True),  # failure: kept regardless of duration
        ("error", 1, 0.0, 0.5, True),  # error: kept regardless of duration
        ("rerun_passed", 3, 0.1, 0.5, True),  # rerun: kept regardless of duration
    ],
)
def test_should_emit(outcome: str, attempts: int, duration: float, threshold: float, expected: bool) -> None:
    test = _testcase(outcome=outcome, attempts=attempts, duration=duration)
    assert report_test_timings.should_emit(test, threshold) is expected


def test_filter_shards_preserves_parse_time_test_windows(tmp_path: Path) -> None:
    _write_shard_xml(
        tmp_path / "junit-results-backend-core-1",
        filename="junit-core.xml",
        timestamp="2026-05-04T10:00:00",
        time="10.0",
        body="""\
            <testcase classname="pkg.t.T" name="test_fast_before" time="0.1"/>
            <testcase classname="pkg.t.T" name="test_slow" time="2.0"/>
            <testcase classname="pkg.t.T" name="test_rerun" time="0.2"><rerunFailure message="x"/></testcase>
            <testcase classname="pkg.t.T" name="test_fail" time="0.1"><failure message="x"/></testcase>
        """,
    )

    filtered = report_test_timings.filter_shards(
        report_test_timings.collect_shards(tmp_path),
        min_duration_seconds=0.5,
    )

    assert [test.name for test in filtered[0].tests] == ["test_slow", "test_rerun", "test_fail"]
    assert filtered[0].tests[0].start == datetime(2026, 5, 4, 10, 0, 0, 100000, tzinfo=UTC)
    assert filtered[0].tests[0].end == datetime(2026, 5, 4, 10, 0, 2, 100000, tzinfo=UTC)
    assert filtered[0].tests[1].start == datetime(2026, 5, 4, 10, 0, 2, 100000, tzinfo=UTC)
    assert filtered[0].tests[2].start == datetime(2026, 5, 4, 10, 0, 2, 300000, tzinfo=UTC)


class _FakeSpan:
    def __init__(self, name: str, start_time: int) -> None:
        self.name = name
        self.start_time = start_time
        self.end_time: int | None = None
        self.attributes: dict[str, str | int | float] = {}

    def set_attribute(self, key: str, value: str | int | float) -> None:
        self.attributes[key] = value

    def set_status(self, status: object) -> None:
        pass

    def end(self, end_time: int) -> None:
        self.end_time = end_time


class _FakeTracer:
    def __init__(self) -> None:
        self.spans: list[_FakeSpan] = []

    def start_span(self, name: str, start_time: int) -> _FakeSpan:
        span = _FakeSpan(name, start_time)
        self.spans.append(span)
        return span


@contextmanager
def _noop_use_span(span: _FakeSpan, end_on_exit: bool = False) -> Iterator[None]:
    yield


def test_emit_shard_span_uses_stored_test_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime(2026, 5, 4, 10, 0, 0, tzinfo=UTC)
    shard = report_test_timings.Shard(
        info=report_test_timings.ArtifactInfo(
            path=Path("junit-results-backend-core-1"),
            suite="backend",
            segment="core",
            group=1,
            total=1,
        ),
        junit_filename="junit-core.xml",
        start=start,
        end=start + timedelta(seconds=10),
        testcase_seconds=2.1,
        overhead_seconds=7.9,
        tests=[
            _testcase(name="slow", duration=2.0, start=start + timedelta(seconds=0.1)),
            _testcase(
                name="fail",
                outcome="failed",
                duration=0.1,
                start=start + timedelta(seconds=2.3),
            ),
        ],
    )
    tracer = _FakeTracer()
    monkeypatch.setattr(report_test_timings.trace, "use_span", _noop_use_span)

    has_error = report_test_timings._emit_shard_span(tracer, shard, "Backend CI / core (1)")

    assert has_error is True
    assert [span.name for span in tracer.spans] == ["Backend CI / core (1)", "m::slow", "m::fail"]
    assert tracer.spans[0].attributes["shard.setup_seconds"] == 0.0
    assert tracer.spans[1].start_time == report_test_timings._to_ns(start + timedelta(seconds=0.1))
    assert tracer.spans[1].end_time == report_test_timings._to_ns(start + timedelta(seconds=2.1))
    assert tracer.spans[2].start_time == report_test_timings._to_ns(start + timedelta(seconds=2.3))
    assert tracer.spans[2].end_time == report_test_timings._to_ns(start + timedelta(seconds=2.4))
    assert tracer.spans[0].attributes["shard.testcase_seconds"] == pytest.approx(2.1)
    assert tracer.spans[0].attributes["shard.overhead_seconds"] == pytest.approx(7.9)


def test_emit_shard_span_emits_setup_span_when_setup_seconds_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the posthog-junit-timings plugin reported setup_seconds, a sibling `setup`
    span covers the pre-first-test gap. Without this, the cursor-based reconstruction
    would visually attribute that gap to the first test."""
    start = datetime(2026, 5, 4, 10, 0, 0, tzinfo=UTC)
    shard = report_test_timings.Shard(
        info=report_test_timings.ArtifactInfo(
            path=Path("junit-results-backend-core-1"),
            suite="backend",
            segment="core",
            group=1,
            total=1,
        ),
        junit_filename="junit-core.xml",
        start=start,
        end=start + timedelta(seconds=10),
        testcase_seconds=2.0,
        overhead_seconds=8.0,
        tests=[_testcase(name="slow", duration=2.0, start=start + timedelta(seconds=3.5))],
        setup_seconds=3.5,
    )
    tracer = _FakeTracer()
    monkeypatch.setattr(report_test_timings.trace, "use_span", _noop_use_span)

    report_test_timings._emit_shard_span(tracer, shard, "Backend CI / core (1)")

    assert [span.name for span in tracer.spans] == ["Backend CI / core (1)", "setup", "m::slow"]
    setup_span = tracer.spans[1]
    assert setup_span.start_time == report_test_timings._to_ns(start)
    assert setup_span.end_time == report_test_timings._to_ns(start + timedelta(seconds=3.5))
    assert setup_span.attributes["shard.setup_seconds"] == pytest.approx(3.5)
    assert tracer.spans[0].attributes["shard.setup_seconds"] == pytest.approx(3.5)


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
    assert attrs["ci.branch"] == "worktree-per-test-telemetry-junit"
    assert attrs["ci.pr_number"] == 57216
    assert attrs["ci.run_url"] == "https://github.com/PostHog/posthog/actions/runs/25218527467"


def test_workflow_resource_attributes_branch_on_push(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF_NAME", "master")

    attrs = report_test_timings.workflow_resource_attributes()

    assert attrs["ci.ref_name"] == "master"
    assert attrs["ci.branch"] == "master"


# ---------- trace id ----------


def test_deterministic_trace_id_is_stable_across_processes() -> None:
    a = report_test_timings.deterministic_trace_id("25218527467", "1", "backend:core:1")
    b = report_test_timings.deterministic_trace_id("25218527467", "1", "backend:core:1")
    assert a == b
    # Different attempt -> different trace id (so reruns of the same workflow run id are isolated).
    assert report_test_timings.deterministic_trace_id("25218527467", "2", "backend:core:1") != a
    # Different job -> different trace id (so each job in a run is its own trace).
    assert report_test_timings.deterministic_trace_id("25218527467", "1", "backend:core:2") != a
    # Result fits in 128 bits.
    assert 0 <= a < 2**128


# ---------- per-job trace naming ----------


def _artifact(suite: str, segment: str, group: int | None) -> report_test_timings.ArtifactInfo:  # type: ignore[name-defined]
    return report_test_timings.ArtifactInfo(
        path=Path(f"junit-results-{suite}"), suite=suite, segment=segment, group=group, total=None
    )


@pytest.mark.parametrize(
    "suite,segment,group,expected",
    [
        ("backend", "core", 29, "Backend CI / core (29)"),
        ("backend", "temporal", 1, "Backend CI / temporal (1)"),
        ("async-migrations", "async-migrations", None, "Backend CI / async-migrations"),
    ],
)
def test_job_trace_name(suite: str, segment: str, group: int | None, expected: str) -> None:
    assert report_test_timings.job_trace_name("Backend CI", _artifact(suite, segment, group)) == expected


def test_job_trace_key_distinguishes_jobs() -> None:
    key = report_test_timings.job_trace_key
    assert key(_artifact("backend", "core", 1)) != key(_artifact("backend", "core", 2))
    assert key(_artifact("backend", "core", 1)) != key(_artifact("backend", "temporal", 1))
    assert key(_artifact("backend", "core", 1)) == key(_artifact("backend", "core", 1))
