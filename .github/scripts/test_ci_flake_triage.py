from __future__ import annotations

import pytest

from ci_flake_overseer import Decision, ExternalCommandError, Job, Step, WorkflowRun, classify_job
from ci_flake_triage import (
    COMMENT_MARKER,
    FlakeMatch,
    TriagedJob,
    Verdict,
    extract_failure_queries,
    is_aggregator_rollup,
    render_comment,
    significant_query_terms,
    triage_jobs,
    verdict_for,
)


class _FakeHistory:
    # Stand-in for the Mendral-backed provider: returns a canned match, or raises
    # the given exception to exercise graceful degradation. Records its calls so a
    # test can assert it was (or wasn't) consulted.
    def __init__(self, result: FlakeMatch | Exception | None) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], str, str]] = []

    def lookup(self, queries: tuple[str, ...], workflow_name: str, log: str) -> FlakeMatch | None:
        self.calls.append((queries, workflow_name, log))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_job(
    name: str,
    *,
    conclusion: str = "failure",
    failed_step: str = "Run Core tests",
) -> Job:
    return Job(
        id=123,
        name=name,
        conclusion=conclusion,
        run_attempt=1,
        html_url="https://github.com/PostHog/posthog/actions/runs/1/job/123",
        started_at="2026-06-05T21:00:00Z",
        steps=(Step(name=failed_step, conclusion="failure"),),
    )


def make_workflow_run() -> WorkflowRun:
    return WorkflowRun(
        id=999,
        workflow_id=42,
        name="Backend CI",
        conclusion="failure",
        head_sha="abc123",
        run_attempt=1,
        html_url="https://github.com/PostHog/posthog/actions/runs/999",
    )


@pytest.mark.parametrize(
    ("decision_action", "cleared", "expected"),
    [
        pytest.param("skip deterministic", False, Verdict.REAL_DETERMINISTIC, id="lint-is-real"),
        pytest.param("skip non-test", False, Verdict.INFRA_NON_TEST, id="build-is-infra"),
        pytest.param("observe", False, Verdict.TEST_UNRESOLVED, id="test-fail-unresolved"),
        pytest.param("observe", True, Verdict.FLAKE_PROVEN, id="test-cleared-on-rerun-is-proven-flake"),
        # A deterministic failure that happened to clear on rerun is still "real":
        # the cleared signal only promotes test-runner failures, never lint/types.
        pytest.param("skip deterministic", True, Verdict.REAL_DETERMINISTIC, id="cleared-deterministic-stays-real"),
    ],
)
def test_verdict_for(decision_action: str, cleared: bool, expected: Verdict) -> None:
    decision = Decision(action=decision_action, reason="", job=make_job("x"))  # type: ignore[arg-type]
    assert verdict_for(decision, cleared_on_rerun=cleared) == expected


def test_triage_jobs_skips_non_failed_and_classifies_real_vs_flake() -> None:
    jobs = (
        make_job("Validate migrations", failed_step="Check migrations"),  # real
        make_job("Django tests (core) 12", failed_step="Run core tests"),  # test -> flake bucket
        make_job("Django tests (core) 7", conclusion="success"),  # ignored: not failed
    )
    triaged = triage_jobs(jobs, cleared_job_names=frozenset())
    by_name = {t.job.name: t.verdict for t in triaged}
    assert by_name == {
        "Validate migrations": Verdict.REAL_DETERMINISTIC,
        "Django tests (core) 12": Verdict.TEST_UNRESOLVED,
    }


def test_triage_jobs_marks_cleared_job_as_proven_flake() -> None:
    job = make_job("Django tests (core) 12", failed_step="Run core tests")
    [triaged] = triage_jobs((job,), cleared_job_names=frozenset({"Django tests (core) 12"}))
    assert triaged.verdict == Verdict.FLAKE_PROVEN
    assert triaged.rerun_clears is True


@pytest.mark.parametrize(
    ("name", "failed_step", "expected"),
    [
        pytest.param("Django Tests Pass", "Check dependency results", True, id="rollup-by-name-and-step"),
        pytest.param("Frontend Tests Pass", "Check outcomes", True, id="rollup-frontend"),
        pytest.param("Python code quality checks", "Check Python CI status", True, id="rollup-python"),
        pytest.param("Django tests (core) 12", "Run core tests", False, id="real-shard-kept"),
        # The ")" suffix means the anchored job pattern can't swallow a real worker job.
        pytest.param(
            "Repo checks (depot-ubuntu-latest)", "Check module boundaries (tach)", False, id="repo-checks-kept"
        ),
    ],
)
def test_is_aggregator_rollup(name: str, failed_step: str, expected: bool) -> None:
    assert is_aggregator_rollup(make_job(name, failed_step=failed_step)) is expected


def test_triage_drops_aggregator_so_only_the_real_shard_remains() -> None:
    jobs = (
        make_job("Django tests (core) 12", failed_step="Run core tests"),
        make_job("Django Tests Pass", failed_step="Check dependency results"),
    )
    triaged = triage_jobs(jobs, cleared_job_names=frozenset())
    assert [t.job.name for t in triaged] == ["Django tests (core) 12"]


_LOG = "FAILED posthog/test_foo.py::TestBar::test_baz\n"


def test_flake_history_upgrades_test_failure_to_known_flake() -> None:
    history = _FakeHistory(FlakeMatch(insight_id="ci-123", title="Flaky temporal job", confidence=92))
    [triaged] = triage_jobs(
        (make_job("Django tests (core) 12", failed_step="Run core tests"),),
        cleared_job_names=frozenset(),
        workflow_name="Backend CI",
        history=history,
        log_for=lambda _job: _LOG,
    )
    assert triaged.verdict == Verdict.FLAKE_KNOWN
    assert triaged.rerun_clears is True
    assert "92% confidence" in triaged.detail and "ci-123" in triaged.detail
    assert history.calls and history.calls[0][1] == "Backend CI"


def test_flake_history_failure_degrades_to_plain_test_verdict() -> None:
    history = _FakeHistory(ExternalCommandError("mendral: command not found"))
    [triaged] = triage_jobs(
        (make_job("Django tests (core) 12", failed_step="Run core tests"),),
        cleared_job_names=frozenset(),
        workflow_name="Backend CI",
        history=history,
        log_for=lambda _job: _LOG,
    )
    assert triaged.verdict == Verdict.TEST_UNRESOLVED


def test_flake_history_not_consulted_for_real_failures() -> None:
    history = _FakeHistory(FlakeMatch(insight_id="x", title="y", confidence=99))
    [triaged] = triage_jobs(
        (make_job("Validate migrations", failed_step="Check migrations"),),
        cleared_job_names=frozenset(),
        workflow_name="Backend CI",
        history=history,
        log_for=lambda _job: _LOG,
    )
    assert triaged.verdict == Verdict.REAL_DETERMINISTIC
    assert history.calls == []  # a rerun can't fix a deterministic check; never asked


def test_extract_failure_queries_finds_pytest_signature() -> None:
    queries = extract_failure_queries("some noise\nFAILED posthog/test_foo.py::TestBar::test_baz\nmore noise\n")
    assert "posthog/test_foo.py::TestBar::test_baz" in queries


def test_significant_query_terms_prefers_test_names_and_constants() -> None:
    assert significant_query_terms("FAILED test_widget_renders") == ("test_widget_renders",)
    assert significant_query_terms("CONNECTION_TIMEOUT raised") == ("CONNECTION_TIMEOUT",)


def test_render_comment_returns_none_when_nothing_triaged() -> None:
    assert render_comment(make_workflow_run(), []) is None


def test_render_comment_groups_real_and_flaky_with_marker_and_action() -> None:
    triaged = [
        TriagedJob(make_job("Django tests (core) 12"), Verdict.TEST_UNRESOLVED, "test-runner failure"),
        TriagedJob(make_job("Validate migrations", failed_step="Check migrations"), Verdict.REAL_DETERMINISTIC, "det"),
    ]
    body = render_comment(make_workflow_run(), triaged)
    assert body is not None
    assert body.startswith(COMMENT_MARKER)
    assert "Backend CI" in body
    assert "🟡" in body and "🔴" in body
    # Both a flaky and a real failure present -> the action tells the author to fix first.
    assert "fix the 1 real failure" in body


def test_render_comment_all_flaky_recommends_rerun() -> None:
    triaged = [TriagedJob(make_job("Django tests (core) 12"), Verdict.FLAKE_PROVEN, "proven flake")]
    body = render_comment(make_workflow_run(), triaged)
    assert body is not None
    assert "Real failures — a rerun won't help" not in body
    assert "most likely flaky" in body


def test_render_comment_all_real_warns_rerun_wont_help() -> None:
    triaged = [
        TriagedJob(make_job("Frontend lint", failed_step="Lint with Oxlint"), Verdict.REAL_DETERMINISTIC, "det"),
    ]
    body = render_comment(make_workflow_run(), triaged)
    assert body is not None
    assert "rerunning alone won't make CI green" in body


def test_classifier_reuse_stays_in_lockstep_with_overseer() -> None:
    # The triage verdict must derive from the overseer's classifier, not a fork of it:
    # a job the overseer calls deterministic must never land in the flaky bucket.
    job = make_job("Validate OpenAPI types", failed_step="Check and update OpenAPI types")
    assert classify_job(job).action == "skip deterministic"
    [triaged] = triage_jobs((job,), cleared_job_names=frozenset({job.name}))
    assert triaged.verdict == Verdict.REAL_DETERMINISTIC
    assert triaged.rerun_clears is False
