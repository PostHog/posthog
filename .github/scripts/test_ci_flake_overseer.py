from __future__ import annotations

import json

import pytest

import ci_flake_overseer
from ci_flake_overseer import (
    DECISION_EVENT,
    OUTCOME_EVENT,
    Decision,
    Job,
    Step,
    WorkflowRun,
    build_decision_events,
    capture_events,
    classify_job,
    is_test_job_failure,
    report_rerun_outcomes,
    rerun_outcome_label,
)


def make_job(
    name: str,
    *,
    run_attempt: int = 1,
    conclusion: str = "failure",
    failed_step: str = "Run Core tests",
    started_at: str = "2026-06-05T21:00:00Z",
) -> Job:
    return Job(
        id=123,
        name=name,
        conclusion=conclusion,
        run_attempt=run_attempt,
        html_url="https://github.com/PostHog/posthog/actions/runs/1/job/123",
        started_at=started_at,
        steps=(Step(name=failed_step, conclusion="failure"),),
    )


def make_workflow_run(run_attempt: int = 1, *, head_branch: str = "", event: str = "pull_request") -> WorkflowRun:
    return WorkflowRun(
        id=999,
        workflow_id=42,
        name="Backend CI",
        conclusion="failure",
        head_sha="abc123",
        run_attempt=run_attempt,
        html_url="https://github.com/PostHog/posthog/actions/runs/999",
        head_branch=head_branch,
        event=event,
    )


@pytest.mark.parametrize(
    ("job", "expected_action", "expected_reason_fragment"),
    [
        pytest.param(
            make_job("Repo checks (depot-ubuntu-latest)", failed_step="Check module boundaries (tach)"),
            "skip deterministic",
            "deterministic",
            id="deterministic-repo-checks",
        ),
        pytest.param(
            make_job("Validate OpenAPI types", failed_step="Check and update OpenAPI types"),
            "skip deterministic",
            "deterministic",
            id="deterministic-openapi",
        ),
        pytest.param(
            make_job("Frontend lint", failed_step="Lint with Oxlint"),
            "skip deterministic",
            "deterministic",
            id="deterministic-lint",
        ),
        pytest.param(
            make_job("Validate migrations", failed_step="Check migrations"),
            "skip deterministic",
            "deterministic",
            id="deterministic-migrations",
        ),
        pytest.param(
            make_job("Build and deploy", failed_step="Compile assets"),
            "skip non-test",
            "not an allowlisted test runner",
            id="non-test-job",
        ),
        pytest.param(
            make_job("Django tests - Temporal (1/1)", failed_step="Run Temporal tests"),
            "observe",
            "test job failure",
            id="observed-test-job",
        ),
    ],
)
def test_classify_job(job: Job, expected_action: str, expected_reason_fragment: str) -> None:
    decision = classify_job(job)

    assert decision.action == expected_action
    assert expected_reason_fragment in decision.reason


@pytest.mark.parametrize(
    ("job_name", "failed_step", "expected"),
    [
        pytest.param("Django tests - Temporal (1/1)", "Run Core tests", True, id="test-job-and-test-step"),
        pytest.param(
            "Django tests - Temporal (1/1)", "Stop containers", True, id="test-job-nontest-step-falls-back-to-name"
        ),
        pytest.param("Build and deploy", "Run Playwright tests", True, id="nontest-job-test-step"),
        pytest.param("Build and deploy", "Compile assets", False, id="nontest-job-and-nontest-step"),
    ],
)
def test_is_test_job_failure(job_name: str, failed_step: str, expected: bool) -> None:
    assert is_test_job_failure(make_job(job_name, failed_step=failed_step)) is expected


def test_build_decision_events_one_event_per_decision() -> None:
    decisions = (
        classify_job(make_job("Django tests - Temporal (1/1)")),
        classify_job(make_job("Build and deploy", failed_step="Compile assets")),
    )

    events = build_decision_events("PostHog/posthog", make_workflow_run(), decisions)

    assert [event["event"] for event in events] == [DECISION_EVENT, DECISION_EVENT]
    assert all(event["distinct_id"] == "PostHog/posthog" for event in events)
    first = events[0]["properties"]
    assert first["action"] == "observe"
    assert first["workflow_name"] == "Backend CI"
    assert first["job_name"] == "Django tests - Temporal (1/1)"
    assert first["$groups"] == {"workflow_run": "999"}
    assert first["classified_via"] == "job_name"
    assert first["job_conclusion"] == "failure"
    assert first["failed_steps"] == ["Run Core tests"]
    assert first["$insert_id"] == "decision:999:1:123"
    assert events[1]["properties"]["action"] == "skip non-test"
    assert events[1]["properties"]["classified_via"] is None


@pytest.mark.parametrize(
    ("conclusion", "expected"),
    [
        pytest.param("success", "cleared", id="success-cleared"),
        pytest.param("failure", "still_failing", id="failure-still-failing"),
        pytest.param("timed_out", "still_failing", id="timed-out-still-failing"),
        pytest.param(None, "unknown", id="missing-unknown"),
        pytest.param("cancelled", "unknown", id="cancelled-unknown"),
    ],
)
def test_rerun_outcome_label(conclusion: str | None, expected: str) -> None:
    assert rerun_outcome_label(conclusion) == expected


def test_report_rerun_outcomes_empty_on_first_attempt() -> None:
    assert report_rerun_outcomes("PostHog/posthog", make_workflow_run(run_attempt=1)) == []


@pytest.mark.parametrize(
    ("current_conclusion", "expected_outcome"),
    [
        pytest.param("success", "cleared", id="rerun-cleared"),
        pytest.param("failure", "still_failing", id="rerun-still-failing"),
        pytest.param("timed_out", "still_failing", id="rerun-timed-out"),
    ],
)
def test_report_rerun_outcomes_attributes_prior_test_failure(
    monkeypatch: pytest.MonkeyPatch, current_conclusion: str, expected_outcome: str
) -> None:
    job_name = "Django tests - Temporal (1/1)"

    def fake_fetch_jobs(repo: str, run_id: int, attempt: int, *, strict: bool = False) -> tuple[Job, ...]:
        if attempt == 1:
            return (make_job(job_name, conclusion="failure", started_at="2026-06-05T21:00:00Z"),)
        # Advanced started_at: this attempt genuinely re-executed the job.
        return (make_job(job_name, conclusion=current_conclusion, started_at="2026-06-05T22:00:00Z"),)

    monkeypatch.setattr(ci_flake_overseer, "fetch_jobs", fake_fetch_jobs)

    events = report_rerun_outcomes("PostHog/posthog", make_workflow_run(run_attempt=2))

    assert len(events) == 1
    assert events[0]["event"] == OUTCOME_EVENT
    props = events[0]["properties"]
    assert props["outcome"] == expected_outcome
    assert props["job_name"] == job_name
    assert props["prior_conclusion"] == "failure"
    assert props["prior_attempt"] == 1
    assert props["attempt"] == 2
    assert props["$insert_id"] == f"outcome:999:2:{job_name}"


def test_report_rerun_outcomes_not_rerun_when_started_at_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    # The regression this fix targets: a failed job carried over (never re-executed) keeps its prior
    # started_at and conclusion. It must read as `not_rerun`, never `still_failing`.
    job_name = "Django tests - Temporal (1/1)"

    def fake_fetch_jobs(repo: str, run_id: int, attempt: int, *, strict: bool = False) -> tuple[Job, ...]:
        return (make_job(job_name, conclusion="failure", started_at="2026-06-05T21:00:00Z"),)

    monkeypatch.setattr(ci_flake_overseer, "fetch_jobs", fake_fetch_jobs)

    events = report_rerun_outcomes("PostHog/posthog", make_workflow_run(run_attempt=2))

    assert len(events) == 1
    assert events[0]["properties"]["outcome"] == "not_rerun"


def test_report_rerun_outcomes_unknown_when_job_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    job_name = "Django tests - Temporal (1/1)"

    def fake_fetch_jobs(repo: str, run_id: int, attempt: int, *, strict: bool = False) -> tuple[Job, ...]:
        if attempt == 1:
            return (make_job(job_name, conclusion="failure"),)
        return ()  # job missing from the re-run attempt

    monkeypatch.setattr(ci_flake_overseer, "fetch_jobs", fake_fetch_jobs)

    events = report_rerun_outcomes("PostHog/posthog", make_workflow_run(run_attempt=2))

    assert len(events) == 1
    assert events[0]["properties"]["outcome"] == "unknown"


def test_report_rerun_outcomes_unknown_when_current_name_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    job_name = "Django tests - Temporal (1/1)"

    def fake_fetch_jobs(repo: str, run_id: int, attempt: int, *, strict: bool = False) -> tuple[Job, ...]:
        if attempt == 1:
            return (make_job(job_name, conclusion="failure"),)
        # Two current jobs share a name: ambiguous, so it can't be paired and must read as unknown.
        return (
            make_job(job_name, conclusion="success", started_at="2026-06-05T22:00:00Z"),
            make_job(job_name, conclusion="failure", started_at="2026-06-05T22:00:00Z"),
        )

    monkeypatch.setattr(ci_flake_overseer, "fetch_jobs", fake_fetch_jobs)

    events = report_rerun_outcomes("PostHog/posthog", make_workflow_run(run_attempt=2))

    assert len(events) == 1
    assert events[0]["properties"]["outcome"] == "unknown"


@pytest.mark.parametrize(
    ("head_branch", "event", "expected_is_master"),
    [
        pytest.param("master", "push", True, id="master-is-master"),
        pytest.param("main", "push", True, id="main-is-master"),
        pytest.param("some-feature", "pull_request", False, id="pr-branch-not-master"),
    ],
)
def test_build_decision_events_is_master(head_branch: str, event: str, expected_is_master: bool) -> None:
    decisions = (classify_job(make_job("Django tests - Temporal (1/1)")),)

    events = build_decision_events(
        "PostHog/posthog", make_workflow_run(head_branch=head_branch, event=event), decisions
    )

    props = events[0]["properties"]
    assert props["is_master"] is expected_is_master
    assert props["trigger_event"] == event


def test_report_rerun_outcomes_ignores_non_test_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch_jobs(repo: str, run_id: int, attempt: int, *, strict: bool = False) -> tuple[Job, ...]:
        return (make_job("Build and deploy", conclusion="failure", failed_step="Compile assets"),)

    monkeypatch.setattr(ci_flake_overseer, "fetch_jobs", fake_fetch_jobs)

    assert report_rerun_outcomes("PostHog/posthog", make_workflow_run(run_attempt=2)) == []


def _raise_if_called(*args: object, **kwargs: object) -> None:
    raise AssertionError("telemetry should not POST")


def test_capture_events_noop_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ci_flake_overseer.urllib.request, "urlopen", _raise_if_called)

    capture_events("", "https://us.i.posthog.com", [{"event": DECISION_EVENT}])


def test_capture_events_noop_without_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ci_flake_overseer.urllib.request, "urlopen", _raise_if_called)

    capture_events("phc_test", "https://us.i.posthog.com", [])


def test_capture_events_posts_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    def fake_urlopen(request: object, timeout: object = None) -> FakeResponse:
        captured["url"] = request.full_url  # type: ignore[attr-defined]
        captured["body"] = json.loads(request.data.decode())  # type: ignore[attr-defined]
        return FakeResponse()

    monkeypatch.setattr(ci_flake_overseer.urllib.request, "urlopen", fake_urlopen)
    events = [{"event": DECISION_EVENT, "distinct_id": "PostHog/posthog", "properties": {}}]

    capture_events("phc_test", "https://us.i.posthog.com/", events)

    assert captured["url"] == "https://us.i.posthog.com/batch/"
    assert captured["body"] == {"api_key": "phc_test", "batch": events}


def test_decision_is_minimal_dataclass() -> None:
    decision = Decision(action="observe", reason="x", job=make_job("Django tests - Temporal (1/1)"))
    assert decision.action == "observe"
