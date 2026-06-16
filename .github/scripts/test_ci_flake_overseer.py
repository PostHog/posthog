from __future__ import annotations

import pytest

from ci_flake_overseer import Decision, FlakeMatch, InsightsSource, Job, Step, classify_job


class StaticInsights:
    def __init__(self, match: FlakeMatch | None) -> None:
        self.match = match
        self.queries: tuple[str, ...] = ()

    def find_flake(self, queries: tuple[str, ...], workflow_name: str, job_name: str, log: str) -> FlakeMatch | None:
        self.queries = queries
        return self.match


def make_job(
    name: str,
    *,
    run_attempt: int = 1,
    failed_step: str = "Run Core tests",
) -> Job:
    return Job(
        id=123,
        name=name,
        conclusion="failure",
        run_attempt=run_attempt,
        html_url="https://github.com/PostHog/posthog/actions/runs/1/job/123",
        steps=(Step(name=failed_step, conclusion="failure"),),
    )


def known_flake() -> FlakeMatch:
    return FlakeMatch(
        insight_id="01KNOWNFLAKE",
        title="Flaky test: test_acheck_query_found ClickHouse query ID collision",
        confidence=85,
        source="test",
        matched_query="test_acheck_query_found",
        summary="test_acheck_query_found fails intermittently",
    )


def classify(job: Job, log: str, insights: InsightsSource) -> Decision:
    return classify_job(
        job,
        log,
        insights,
        workflow_name="Backend CI",
        max_reruns_per_job=1,
    )


def test_known_flaky_test_failure_is_rerun_eligible() -> None:
    insights = StaticInsights(known_flake())
    decision = classify(
        make_job("Django tests - Temporal (1/1)"),
        "FAILED posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found\nQUERY_WITH_SAME_ID_IS_ALREADY_RUNNING",
        insights,
    )

    assert decision.action == "rerun"
    assert decision.match == known_flake()
    assert "test_acheck_query_found" in insights.queries


@pytest.mark.parametrize(
    ("job", "log", "expected_reason"),
    [
        (
            make_job("Repo checks (depot-ubuntu-latest)", failed_step="Check module boundaries (tach)"),
            "tach check --dependencies --interfaces\nRepo checks failed deterministically",
            "deterministic",
        ),
        (
            make_job("Validate OpenAPI types", failed_step="Check and update OpenAPI types"),
            "OpenAPI types are out of date. To fix, run locally: hogli build:openapi",
            "deterministic",
        ),
        (
            make_job("Frontend lint", failed_step="Lint with Oxlint"),
            "oxlint found errors",
            "deterministic",
        ),
        (
            make_job("Frontend typescript checks", failed_step="Run typescript with strict"),
            "pnpm --filter=@posthog/frontend typescript:check failed",
            "deterministic",
        ),
        (
            make_job("Validate migrations", failed_step="Check migrations"),
            "python manage.py makemigrations --check --dry-run failed",
            "deterministic",
        ),
    ],
)
def test_deterministic_failures_are_not_rerun(job: Job, log: str, expected_reason: str) -> None:
    decision = classify(job, log, StaticInsights(known_flake()))

    assert decision.action == "skip deterministic"
    assert expected_reason in decision.reason


def test_unknown_test_failure_is_not_rerun() -> None:
    decision = classify(
        make_job("Django tests - Core (1/1)"),
        "FAILED posthog/test/test_something.py::test_new_regression\nAssertionError: expected 1 == 2",
        StaticInsights(None),
    )

    assert decision.action == "skip unknown"
    assert "no high-confidence known flaky signature matched" in decision.reason


def test_already_rerun_attempt_is_not_rerun() -> None:
    decision = classify(
        make_job("Django tests - Temporal (1/1)", run_attempt=2),
        "FAILED posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found\nQUERY_WITH_SAME_ID_IS_ALREADY_RUNNING",
        StaticInsights(known_flake()),
    )

    assert decision.action == "skip cap reached"
    assert "automatic rerun cap 1" in decision.reason


def test_prior_same_sha_rerun_cap_is_not_rerun() -> None:
    decision = classify_job(
        make_job("Django tests - Temporal (1/1)"),
        "FAILED posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found\nQUERY_WITH_SAME_ID_IS_ALREADY_RUNNING",
        StaticInsights(known_flake()),
        workflow_name="Backend CI",
        max_reruns_per_job=1,
        cap_reached_reason="matching job already reached attempt 2 for head SHA abc123",
    )

    assert decision.action == "skip cap reached"
    assert "matching job already reached attempt 2" in decision.reason
