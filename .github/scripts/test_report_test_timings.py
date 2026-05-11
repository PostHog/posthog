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
) -> report_test_timings.TestCase:
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


def test_emit_shard_span_uses_stored_test_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSpan:
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

    class FakeTracer:
        def __init__(self) -> None:
            self.spans: list[FakeSpan] = []

        def start_span(self, name: str, start_time: int) -> FakeSpan:
            span = FakeSpan(name, start_time)
            self.spans.append(span)
            return span

    @contextmanager
    def use_span(span: FakeSpan, end_on_exit: bool = False) -> Iterator[None]:
        yield

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
    tracer = FakeTracer()
    monkeypatch.setattr(report_test_timings.trace, "use_span", use_span)

    has_error = report_test_timings._emit_shard_span(tracer, shard)

    assert has_error is True
    assert [span.name for span in tracer.spans] == ["core-1", "m::slow", "m::fail"]
    assert tracer.spans[1].start_time == report_test_timings._to_ns(start + timedelta(seconds=0.1))
    assert tracer.spans[1].end_time == report_test_timings._to_ns(start + timedelta(seconds=2.1))
    assert tracer.spans[2].start_time == report_test_timings._to_ns(start + timedelta(seconds=2.3))
    assert tracer.spans[2].end_time == report_test_timings._to_ns(start + timedelta(seconds=2.4))
    assert tracer.spans[0].attributes["shard.testcase_seconds"] == pytest.approx(2.1)
    assert tracer.spans[0].attributes["shard.overhead_seconds"] == pytest.approx(7.9)


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
