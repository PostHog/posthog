from __future__ import annotations

import io
import sys
import json
import urllib.error
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

SCRIPT_PATH = Path(__file__).with_name("report_workflow_run_traces.py")
SPEC = importlib.util.spec_from_file_location("report_workflow_run_traces", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
reporter = importlib.util.module_from_spec(SPEC)
# Register before exec so @dataclass can resolve the module via sys.modules.
sys.modules["report_workflow_run_traces"] = reporter
SPEC.loader.exec_module(reporter)

RUN_START = datetime(2026, 8, 18, 10, 0, 0, tzinfo=UTC)


def _iso(offset_seconds: int) -> str:
    return (RUN_START + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def _raw_step(*, number: int = 1, name: str = "Set up job", start: int = 0, end: int = 1, **overrides: Any) -> dict:
    return {
        "number": number,
        "name": name,
        "status": "completed",
        "conclusion": "success",
        "started_at": _iso(start),
        "completed_at": _iso(end),
        **overrides,
    }


def _raw_job(
    *, created: int = 0, start: int = 5, end: int = 60, steps: list[dict] | None = None, **overrides: Any
) -> dict:
    return {
        "id": 1234,
        "name": "build",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.com/PostHog/posthog/actions/runs/1/job/1234",
        "runner_name": "GitHub Actions 1",
        "runner_group_name": "GitHub Actions",
        "labels": ["ubuntu-latest"],
        "created_at": _iso(created),
        "started_at": _iso(start),
        "completed_at": _iso(end),
        "steps": steps if steps is not None else [_raw_step(start=5, end=20)],
        **overrides,
    }


def _raw_run(**overrides: Any) -> dict:
    return {
        "id": 999,
        "run_attempt": 1,
        "name": "Container Images CD",
        "path": ".github/workflows/container-images-cd.yml",
        "workflow_id": 42,
        "run_number": 7,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "display_title": "fix: something",
        "head_sha": "abc123",
        "head_branch": "master",
        "actor": {"login": "trunk-io[bot]"},
        "triggering_actor": {"login": "trunk-io[bot]"},
        "repository": {"full_name": "PostHog/posthog"},
        "html_url": "https://github.com/PostHog/posthog/actions/runs/999",
        "created_at": _iso(0),
        "run_started_at": _iso(0),
        "updated_at": _iso(120),
        **overrides,
    }


class TestTimestampClamping:
    @pytest.mark.parametrize(
        "start_offset,end_offset,expected_duration",
        [
            (5, 60, 55.0),
            (5, 5, 0.0),
            # A skipped job really does report completion a second before it started.
            (20, 19, 0.0),
        ],
    )
    def test_job_duration_never_negative(self, start_offset: int, end_offset: int, expected_duration: float) -> None:
        job = reporter.parse_job(_raw_job(created=0, start=start_offset, end=end_offset, steps=[]))
        assert job is not None
        assert job.duration_seconds == expected_duration
        assert job.end >= job.start

    def test_job_created_never_after_start(self) -> None:
        job = reporter.parse_job(_raw_job(created=30, start=5, end=60, steps=[]))
        assert job is not None
        assert job.queued_seconds >= 0

    def test_step_clamped_into_job_window(self) -> None:
        # Second-granularity step timestamps can overhang the job they belong to.
        job = reporter.parse_job(_raw_job(start=5, end=60, steps=[_raw_step(start=3, end=90)]))
        assert job is not None
        assert job.steps[0].start >= job.start
        assert job.steps[0].end <= job.end

    def test_zero_length_step_is_emitted(self) -> None:
        # 57% of real CI steps complete within the same second; dropping them would
        # gut the waterfall.
        job = reporter.parse_job(_raw_job(steps=[_raw_step(start=10, end=10)]))
        assert job is not None
        assert len(job.steps) == 1
        assert job.steps[0].duration_seconds == 0.0


class TestJobParsing:
    def test_drops_job_without_completed_at(self) -> None:
        assert reporter.parse_job(_raw_job(completed_at=None)) is None

    def test_keeps_job_with_no_steps(self) -> None:
        # Skipped jobs come back with `steps: []`; a skipped job is signal.
        job = reporter.parse_job(_raw_job(conclusion="skipped", steps=[]))
        assert job is not None
        assert job.steps == ()

    def test_missing_started_at_falls_back_to_created(self) -> None:
        job = reporter.parse_job(_raw_job(started_at=None, steps=[]))
        assert job is not None
        assert job.end >= job.start

    def test_steps_sorted_by_number_not_input_order(self) -> None:
        # Real step numbers are non-contiguous (1,2,3,4,5,10,11) and the API order
        # is not guaranteed.
        raw = _raw_job(
            steps=[
                _raw_step(number=11, name="Complete job", start=50, end=51),
                _raw_step(number=1, name="Set up job", start=5, end=6),
                _raw_step(number=10, name="Post checkout", start=45, end=46),
            ]
        )
        job = reporter.parse_job(raw)
        assert job is not None
        assert [step.number for step in job.steps] == [1, 10, 11]

    def test_step_without_timestamps_is_dropped(self) -> None:
        job = reporter.parse_job(_raw_job(steps=[_raw_step(), _raw_step(number=2, completed_at=None)]))
        assert job is not None
        assert [step.number for step in job.steps] == [1]


class TestJobNaming:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("build-images / build cymbal", ("build-images", "build cymbal")),
            ("compute affected images", ("", "")),
            # The callee half can carry another separator; only the first splits.
            ("outer / inner / leaf", ("outer", "inner / leaf")),
        ],
    )
    def test_split_reusable_name(self, name: str, expected: tuple[str, str]) -> None:
        assert reporter.split_reusable_name(name) == expected

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Django tests – Core (6/19)", "Django tests – Core"),
            ("Validate product.yaml owners (ubuntu-latest)", "Validate product.yaml owners"),
            ("compute affected images", "compute affected images"),
            # Strip one group only, so an inner group survives for grouping.
            ("Django tests (FOSS) (3/9)", "Django tests (FOSS)"),
        ],
    )
    def test_job_group_name_strips_one_matrix_suffix(self, name: str, expected: str) -> None:
        assert reporter.job_group_name(name) == expected

    def test_unexpanded_matrix_expression_survives(self) -> None:
        # A skipped matrix job keeps the literal expression as its name.
        job = reporter.parse_job(_raw_job(name="deploy ${{ matrix.release }}", conclusion="skipped", steps=[]))
        assert job is not None
        assert job.name == "deploy ${{ matrix.release }}"
        assert reporter.job_group_name(job.name) == "deploy ${{ matrix.release }}"


class TestResourceAttributes:
    def test_ignores_this_reporters_own_github_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The reporter runs on a cron tick, so its own GITHUB_* describes the tick and
        # not the run being traced. Leaking those in would silently mislabel every span.
        for name, value in {
            "GITHUB_RUN_ID": "SENTINEL_RUN",
            "GITHUB_RUN_ATTEMPT": "SENTINEL_ATTEMPT",
            "GITHUB_WORKFLOW": "SENTINEL_WORKFLOW",
            "GITHUB_SHA": "SENTINEL_SHA",
            "GITHUB_ACTOR": "SENTINEL_ACTOR",
            "GITHUB_RUN_NUMBER": "SENTINEL_NUMBER",
        }.items():
            monkeypatch.setenv(name, value)
        run = reporter.parse_run(_raw_run(), [_raw_job()])
        assert run is not None
        rendered = json.dumps(reporter.run_resource_attributes(run))
        assert "SENTINEL" not in rendered

    def test_carries_traced_run_identity(self) -> None:
        run = reporter.parse_run(_raw_run(), [_raw_job()])
        assert run is not None
        attrs = reporter.run_resource_attributes(run)
        assert attrs["ci.workflow"] == "Container Images CD"
        assert attrs["ci.run_id"] == 999
        assert attrs["ci.sha"] == "abc123"
        assert attrs["ci.branch"] == "master"
        assert attrs["ci.ref"] == "refs/heads/master"
        assert attrs["service.name"] == "ci-workflows"

    def test_drops_empty_values(self) -> None:
        run = reporter.parse_run(_raw_run(head_branch="", display_title=""), [_raw_job()])
        assert run is not None
        attrs = reporter.run_resource_attributes(run)
        assert "ci.branch" not in attrs
        assert "ci.ref" not in attrs


class TestRunParsing:
    def test_end_is_last_job_completion(self) -> None:
        run = reporter.parse_run(
            _raw_run(updated_at=_iso(9999)),
            [_raw_job(id=1, start=5, end=60, steps=[]), _raw_job(id=2, start=5, end=200, steps=[])],
        )
        assert run is not None
        assert run.duration_seconds == 200.0

    def test_counts_dropped_jobs(self) -> None:
        run = reporter.parse_run(_raw_run(), [_raw_job(), _raw_job(id=2, completed_at=None)])
        assert run is not None
        assert len(run.jobs) == 1
        assert run.dropped_jobs == 1

    def test_step_count_sums_jobs(self) -> None:
        run = reporter.parse_run(
            _raw_run(),
            [
                _raw_job(id=1, steps=[_raw_step(), _raw_step(number=2)]),
                _raw_job(id=2, steps=[_raw_step()]),
            ],
        )
        assert run is not None
        assert run.step_count == 3


class TestDeterministicIds:
    def test_trace_id_varies_with_attempt(self) -> None:
        assert reporter.deterministic_trace_id(999, 1) != reporter.deterministic_trace_id(999, 2)

    def test_trace_id_fits_128_bits(self) -> None:
        assert 0 < reporter.deterministic_trace_id(999, 1) < 2**128

    def test_span_id_fits_64_bits_and_is_never_zero(self) -> None:
        for parts in [(999, 1, "run"), (999, 1, "job", 5), (999, 1, "step", 5, 10)]:
            span_id = reporter.deterministic_span_id(*parts)
            assert 0 < span_id < 2**64

    def test_span_ids_distinct_across_kinds(self) -> None:
        ids = {
            reporter.deterministic_span_id(999, 1, "run"),
            reporter.deterministic_span_id(999, 1, "job", 5),
            reporter.deterministic_span_id(999, 1, "queued", 5),
            reporter.deterministic_span_id(999, 1, "step", 5, 1),
        }
        assert len(ids) == 4


class _FakeOpener:
    """Stands in for urllib.request.urlopen, keyed on a substring of the URL."""

    def __init__(self, routes: dict[str, Any], default: Any = None) -> None:
        self.routes = routes
        self.default = default if default is not None else {}
        self.calls: list[str] = []

    def __call__(self, request: Any, timeout: int = 0) -> Any:
        url = request.full_url
        self.calls.append(url)
        for fragment, payload in self.routes.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return _FakeResponse(payload)
        return _FakeResponse(self.default)


class _FakeResponse(io.BytesIO):
    def __init__(self, payload: Any) -> None:
        super().__init__(json.dumps(payload).encode())

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


class TestPagination:
    def test_stops_on_short_page(self) -> None:
        opener = _FakeOpener({"/jobs": {"jobs": [{"id": 1}]}})
        jobs = reporter.fetch_jobs("PostHog/posthog", 1, 1, "t", opener=opener)
        assert len(jobs) == 1
        assert len(opener.calls) == 1

    def test_follows_full_pages(self) -> None:
        # Backend CI is already 91 jobs, so a heavier matrix crosses the page size.
        pages = iter(
            [
                {"jobs": [{"id": i} for i in range(reporter.PER_PAGE)]},
                {"jobs": [{"id": 999}]},
            ]
        )
        jobs = reporter.fetch_jobs(
            "PostHog/posthog", 1, 1, "t", opener=lambda request, timeout=0: _FakeResponse(next(pages))
        )
        assert len(jobs) == reporter.PER_PAGE + 1

    def test_respects_max_pages(self) -> None:
        full = {"jobs": [{"id": i} for i in range(reporter.PER_PAGE)]}
        opener = _FakeOpener({"/jobs": full})
        jobs = reporter.fetch_jobs("PostHog/posthog", 1, 1, "t", opener=opener)
        assert len(jobs) == reporter.PER_PAGE * reporter.MAX_PAGES
        assert len(opener.calls) == reporter.MAX_PAGES


class TestWatermark:
    def test_uses_previous_successful_run_start(self) -> None:
        opener = _FakeOpener(
            {
                f"/workflows/{reporter.SELF_WORKFLOW_FILE}/runs": {
                    "workflow_runs": [
                        {"run_started_at": _iso(600)},
                        {"run_started_at": _iso(300)},
                    ]
                }
            }
        )
        since = reporter.watermark(
            "PostHog/posthog", "t", lookback_hours=6.0, now=RUN_START + timedelta(seconds=900), opener=opener
        )
        assert since == RUN_START + timedelta(seconds=600)

    def test_falls_back_to_lookback_without_history(self) -> None:
        # The very first tick has no prior success and must not wedge.
        opener = _FakeOpener({f"/workflows/{reporter.SELF_WORKFLOW_FILE}/runs": {"workflow_runs": []}})
        now = RUN_START + timedelta(hours=12)
        since = reporter.watermark("PostHog/posthog", "t", lookback_hours=6.0, now=now, opener=opener)
        assert since == now - timedelta(hours=6)

    def test_falls_back_when_history_is_a_404(self) -> None:
        error = urllib.error.HTTPError("u", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        opener = _FakeOpener({f"/workflows/{reporter.SELF_WORKFLOW_FILE}/runs": error})
        now = RUN_START + timedelta(hours=12)
        since = reporter.watermark("PostHog/posthog", "t", lookback_hours=6.0, now=now, opener=opener)
        assert since == now - timedelta(hours=6)

    def test_never_reaches_further_back_than_the_lookback(self) -> None:
        # A long reporter outage must not trigger an unbounded backfill.
        opener = _FakeOpener(
            {f"/workflows/{reporter.SELF_WORKFLOW_FILE}/runs": {"workflow_runs": [{"run_started_at": _iso(0)}]}}
        )
        now = RUN_START + timedelta(days=30)
        since = reporter.watermark("PostHog/posthog", "t", lookback_hours=6.0, now=now, opener=opener)
        assert since == now - timedelta(hours=6)


class TestScan:
    def test_filters_on_updated_at(self) -> None:
        # The API can only filter on `created`, so without the updated_at narrowing
        # every tick would re-emit the whole window.
        opener = _FakeOpener(
            {
                "/actions/runs": {
                    "workflow_runs": [
                        {"id": 1, "updated_at": _iso(100)},
                        {"id": 2, "updated_at": _iso(500)},
                    ]
                }
            }
        )
        fresh = reporter.scan_runs("PostHog/posthog", "t", RUN_START + timedelta(seconds=300), opener=opener)
        assert [run["id"] for run in fresh] == [2]

    def test_includes_runs_updated_exactly_at_the_watermark(self) -> None:
        opener = _FakeOpener({"/actions/runs": {"workflow_runs": [{"id": 1, "updated_at": _iso(300)}]}})
        fresh = reporter.scan_runs("PostHog/posthog", "t", RUN_START + timedelta(seconds=300), opener=opener)
        assert [run["id"] for run in fresh] == [1]

    def test_scopes_the_query_to_master_pushes(self) -> None:
        opener = _FakeOpener({"/actions/runs": {"workflow_runs": []}})
        reporter.scan_runs("PostHog/posthog", "t", RUN_START, opener=opener)
        url = opener.calls[0]
        assert "branch=master" in url
        assert "event=push" in url
        assert "status=completed" in url

    def test_also_scans_the_scheduled_lane_of_cron_covered_workflows(self) -> None:
        # ci-backend.yml runs the per-commit checks on a master push and its test matrices
        # hourly, so a push-only scan drops the heaviest CI workload in the repo.
        workflow_file = reporter.SCHEDULED_MASTER_WORKFLOWS[0]
        opener = _FakeOpener(
            {
                "/actions/runs": {"workflow_runs": [{"id": 1, "updated_at": _iso(400)}]},
                f"/workflows/{workflow_file}/runs": {"workflow_runs": [{"id": 2, "updated_at": _iso(500)}]},
            }
        )
        fresh = reporter.scan_runs("PostHog/posthog", "t", RUN_START, opener=opener)
        # Newest first across both scans, because that is the order --max-runs caps on.
        assert [run["id"] for run in fresh] == [2, 1]
        scheduled_url = next(url for url in opener.calls if workflow_file in url)
        assert "branch=master" in scheduled_url
        assert "event=schedule" in scheduled_url


class TestAttemptSelection:
    def test_selected_attempt_uses_that_attempts_window(self) -> None:
        # Pairing an older attempt's jobs with the latest attempt's `run_started_at` puts
        # every job before the root span starts, which clamps the root to zero length.
        opener = _FakeOpener(
            {
                "/attempts/2/jobs": {"jobs": [_raw_job()]},
                "/attempts/2": _raw_run(run_attempt=2),
                "/actions/runs/999": _raw_run(
                    run_attempt=3, created_at=_iso(10_000), run_started_at=_iso(10_000), updated_at=_iso(10_100)
                ),
            }
        )
        args = reporter.parse_args(["--run-id", "999", "--run-attempt", "2"])
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(reporter.urllib.request, "urlopen", opener)
            collection = reporter.collect_runs(args, "t", RUN_START)

        run = collection.runs[0]
        assert run.attempt == 2
        assert run.duration_seconds == 60.0
        assert run.jobs[0].start >= run.start
        assert run.jobs[0].end <= run.end


class TestApiRetries:
    def test_does_not_retry_a_404(self) -> None:
        # With an empty rate-limit bucket a retry just spends more of it.
        error = urllib.error.HTTPError("u", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        opener = _FakeOpener({"anything": error})
        with pytest.raises(reporter.ApiError) as excinfo:
            reporter._api_get("anything", "t", opener=opener)
        assert excinfo.value.status == 404
        assert len(opener.calls) == 1

    def test_retries_a_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(reporter.time, "sleep", lambda _seconds: None)
        error = urllib.error.HTTPError("u", 503, "Unavailable", {}, None)  # type: ignore[arg-type]
        opener = _FakeOpener({"anything": error})
        with pytest.raises(reporter.ApiError):
            reporter._api_get("anything", "t", opener=opener)
        assert len(opener.calls) == reporter.API_ATTEMPTS


class TestExitStatus:
    """The watermark is this workflow's last *successful* run, so exit status decides
    whether the next tick re-covers the window. A tick that lost traces must not be
    recorded as clean, and a tick with nothing to do must not be recorded as broken."""

    @pytest.mark.parametrize(
        "failure",
        [
            urllib.error.URLError("connection reset"),
            urllib.error.HTTPError("u", 500, "Server Error", {}, None),  # type: ignore[arg-type]
            urllib.error.HTTPError("u", 403, "Forbidden", {}, None),  # type: ignore[arg-type]
        ],
    )
    def test_a_failed_scan_holds_the_watermark(self, failure: Exception, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setattr(reporter.time, "sleep", lambda _seconds: None)
        monkeypatch.setattr(reporter.urllib.request, "urlopen", _FakeOpener({"": failure}))
        assert reporter.main(["--dry-run"]) == reporter.EXIT_INCOMPLETE

    def test_malformed_json_holds_the_watermark(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setattr(reporter.time, "sleep", lambda _seconds: None)

        class _Garbage(io.BytesIO):
            def __enter__(self) -> _Garbage:
                return self

            def __exit__(self, *_: Any) -> None:
                return None

        monkeypatch.setattr(reporter.urllib.request, "urlopen", lambda request, timeout=0: _Garbage(b"not json"))
        assert reporter.main(["--dry-run"]) == reporter.EXIT_INCOMPLETE

    def test_a_missing_github_token_holds_the_watermark(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert reporter.main([]) == reporter.EXIT_INCOMPLETE

    def test_missing_project_tokens_hold_the_watermark(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        for var in reporter.TOKEN_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(
            reporter.urllib.request,
            "urlopen",
            _FakeOpener({"/jobs": {"jobs": [_raw_job()]}, "/actions/runs/999": _raw_run()}),
        )
        assert reporter.main(["--run-id", "999"]) == reporter.EXIT_INCOMPLETE

    def test_a_run_whose_jobs_will_not_load_holds_the_watermark(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setattr(reporter.time, "sleep", lambda _seconds: None)
        monkeypatch.setattr(
            reporter.urllib.request,
            "urlopen",
            _FakeOpener(
                {
                    "/jobs": urllib.error.HTTPError("u", 500, "Server Error", {}, None),  # type: ignore[arg-type]
                    "/actions/runs/999": _raw_run(),
                }
            ),
        )
        assert reporter.main(["--dry-run", "--run-id", "999"]) == reporter.EXIT_INCOMPLETE

    def test_a_rejected_export_holds_the_watermark(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The SDK only logs a rejected batch, so an hour of 403s from the ingest
        # endpoint would otherwise read as a clean tick.
        class _RejectingExporter(SpanExporter):
            def export(self, spans: Any) -> SpanExportResult:
                return SpanExportResult.FAILURE

        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setenv("POSTHOG_DEVEX_PROJECT_API_TOKEN", "p")
        monkeypatch.delenv("POSTHOG_CI_TRACES_EXTRA_TOKEN", raising=False)
        monkeypatch.setattr(reporter, "OTLPSpanExporter", lambda **_kwargs: _RejectingExporter())
        monkeypatch.setattr(
            reporter.urllib.request,
            "urlopen",
            _FakeOpener({"/jobs": {"jobs": [_raw_job()]}, "/actions/runs/999": _raw_run()}),
        )
        assert reporter.main(["--run-id", "999"]) == reporter.EXIT_INCOMPLETE

    def test_an_exporter_that_raises_holds_the_watermark(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A transport failure raises rather than returning FAILURE, and the SDK's batch
        # processor swallows it on its worker thread, so without recording the loss a total
        # outage would read as a clean tick and the watermark would advance past every trace.
        class _RaisingExporter(SpanExporter):
            def export(self, spans: Any) -> SpanExportResult:
                raise ConnectionError("ingest endpoint unreachable")

        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setenv("POSTHOG_DEVEX_PROJECT_API_TOKEN", "p")
        monkeypatch.delenv("POSTHOG_CI_TRACES_EXTRA_TOKEN", raising=False)
        monkeypatch.setattr(reporter, "OTLPSpanExporter", lambda **_kwargs: _RaisingExporter())
        monkeypatch.setattr(
            reporter.urllib.request,
            "urlopen",
            _FakeOpener({"/jobs": {"jobs": [_raw_job()]}, "/actions/runs/999": _raw_run()}),
        )
        assert reporter.main(["--run-id", "999"]) == reporter.EXIT_INCOMPLETE

    def test_a_run_reporting_zero_jobs_advances_the_watermark(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A cancelled run really can report zero jobs, and nothing was lost, so the tick is clean.
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setattr(
            reporter.urllib.request,
            "urlopen",
            _FakeOpener({"/jobs": {"jobs": []}, "/actions/runs/999": _raw_run()}),
        )
        assert reporter.main(["--dry-run", "--run-id", "999"]) == reporter.EXIT_OK


class TestDryRunTree:
    def test_renders_without_touching_an_exporter(self) -> None:
        run = reporter.parse_run(_raw_run(), [_raw_job(name="Build and push PostHog")])
        assert run is not None
        lines = list(reporter.format_span_tree(run))
        assert "Container Images CD" in lines[0]
        assert any("Build and push PostHog" in line for line in lines)


class TestSpanTree:
    """Exercises the real emit path, so an invalid attribute type or a broken
    parent link fails here rather than silently in CI."""

    @staticmethod
    def _emit(run: Any) -> list[Any]:
        exporter = InMemorySpanExporter()
        reporter.emit_trace(run, "http://unused", "token", exporter=exporter)
        return list(exporter.get_finished_spans())

    def test_builds_run_job_step_hierarchy(self) -> None:
        run = reporter.parse_run(
            _raw_run(),
            [_raw_job(name="Build and push PostHog", steps=[_raw_step(name="Set up job", start=5, end=8)])],
        )
        assert run is not None
        spans = self._emit(run)
        by_name = {span.name: span for span in spans}

        root, job, step = by_name["Container Images CD"], by_name["Build and push PostHog"], by_name["Set up job"]
        assert root.parent is None
        assert job.parent.span_id == root.context.span_id
        assert step.parent.span_id == job.context.span_id
        # One trace, so a reader sees the whole run as a single waterfall.
        assert {span.context.trace_id for span in spans} == {reporter.deterministic_trace_id(999, 1)}

    def test_queued_span_covers_the_wait(self) -> None:
        run = reporter.parse_run(_raw_run(), [_raw_job(created=0, start=30, end=60, steps=[])])
        assert run is not None
        queued = next(span for span in self._emit(run) if span.name == "queued")
        assert (queued.end_time - queued.start_time) / 1_000_000_000 == 30.0

    def test_no_queued_span_without_a_wait(self) -> None:
        run = reporter.parse_run(_raw_run(), [_raw_job(created=5, start=5, end=60, steps=[])])
        assert run is not None
        assert not [span for span in self._emit(run) if span.name == "queued"]

    def test_every_span_ends_at_or_after_it_starts(self) -> None:
        # OTLP rejects an inverted window, and skipped jobs report one.
        run = reporter.parse_run(
            _raw_run(conclusion="cancelled"),
            [
                _raw_job(id=1, name="ok", start=5, end=60),
                _raw_job(id=2, name="skipped one", conclusion="skipped", start=20, end=19, steps=[]),
            ],
        )
        assert run is not None
        spans = self._emit(run)
        assert spans
        assert all(span.end_time >= span.start_time for span in spans)

    @pytest.mark.parametrize(
        "conclusion,expected",
        [
            ("failure", "ERROR"),
            ("timed_out", "ERROR"),
            ("startup_failure", "ERROR"),
            ("success", "UNSET"),
            # Master runs get cancelled by concurrency routinely, so marking those Error
            # would bury the runs that actually broke.
            ("cancelled", "UNSET"),
            ("skipped", "UNSET"),
        ],
    )
    def test_root_status_reflects_only_the_failure_family(self, conclusion: str, expected: str) -> None:
        run = reporter.parse_run(_raw_run(conclusion=conclusion), [_raw_job(steps=[])])
        assert run is not None
        root = next(span for span in self._emit(run) if span.name == "Container Images CD")
        assert root.status.status_code.name == expected
        # The conclusion is still queryable even when the span isn't an error.
        assert root.attributes["ci.workflow.conclusion"] == conclusion

    @pytest.mark.parametrize(
        "conclusion,expected",
        [("failure", "ERROR"), ("timed_out", "ERROR"), ("cancelled", "UNSET"), ("skipped", "UNSET")],
    )
    def test_job_status_reflects_only_the_failure_family(self, conclusion: str, expected: str) -> None:
        run = reporter.parse_run(_raw_run(), [_raw_job(conclusion=conclusion, steps=[])])
        assert run is not None
        job = next(span for span in self._emit(run) if span.name == "build")
        assert job.status.status_code.name == expected

    def test_failure_marks_the_step_too(self) -> None:
        run = reporter.parse_run(
            _raw_run(conclusion="failure"),
            [_raw_job(conclusion="failure", steps=[_raw_step(name="boom", conclusion="failure")])],
        )
        assert run is not None
        statuses = {span.name: span.status.status_code.name for span in self._emit(run)}
        assert statuses["boom"] == "ERROR"
        assert statuses["build"] == "ERROR"
        assert statuses["Container Images CD"] == "ERROR"

    def test_reusable_job_records_caller_and_callee(self) -> None:
        run = reporter.parse_run(_raw_run(), [_raw_job(name="build-images / build cymbal", steps=[])])
        assert run is not None
        job = next(span for span in self._emit(run) if span.name == "build-images / build cymbal")
        assert job.attributes["ci.job.caller"] == "build-images"
        assert job.attributes["ci.job.callee"] == "build cymbal"

    def test_labels_are_a_joined_string(self) -> None:
        # A sequence would fragment downstream; one string stays queryable.
        run = reporter.parse_run(_raw_run(), [_raw_job(labels=["depot-ubuntu-24.04", "self-hosted"], steps=[])])
        assert run is not None
        job = next(span for span in self._emit(run) if span.name == "build")
        assert job.attributes["ci.job.labels"] == "depot-ubuntu-24.04,self-hosted"

    def test_span_ids_are_stable_across_emits(self) -> None:
        # A duplicate tick at the watermark boundary re-emits identical spans.
        run = reporter.parse_run(_raw_run(), [_raw_job()])
        assert run is not None
        first = {span.name: span.context.span_id for span in self._emit(run)}
        second = {span.name: span.context.span_id for span in self._emit(run)}
        assert first == second

    def test_span_count_matches_what_is_exported(self) -> None:
        run = reporter.parse_run(
            _raw_run(),
            [_raw_job(id=1, steps=[_raw_step(), _raw_step(number=2)]), _raw_job(id=2, steps=[_raw_step()])],
        )
        assert run is not None
        exporter = InMemorySpanExporter()
        reported = reporter.emit_trace(run, "http://unused", "token", exporter=exporter)
        assert reported == len(exporter.get_finished_spans())


class TestEmissionTokens:
    @pytest.mark.parametrize(
        "env,expected_count",
        [
            ({}, 0),
            ({"POSTHOG_DEVEX_PROJECT_API_TOKEN": "a"}, 1),
            ({"POSTHOG_DEVEX_PROJECT_API_TOKEN": "a", "POSTHOG_CI_TRACES_EXTRA_TOKEN": "b"}, 2),
            # The same token in both vars must not double-emit.
            ({"POSTHOG_DEVEX_PROJECT_API_TOKEN": "a", "POSTHOG_CI_TRACES_EXTRA_TOKEN": "a"}, 1),
        ],
    )
    def test_dedupes_and_skips_empties(self, env: dict[str, str], expected_count: int) -> None:
        assert len(reporter.emission_tokens(env)) == expected_count
