from __future__ import annotations

import pytest

from ci_flake_overseer import (
    MAX_QUERY_COUNT,
    Decision,
    FlakeMatch,
    InsightsSource,
    Job,
    Step,
    classify_job,
    extract_failure_queries,
)


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
    ("job", "log", "insights", "expected_action", "expected_reason_fragment"),
    [
        pytest.param(
            make_job("Repo checks (depot-ubuntu-latest)", failed_step="Check module boundaries (tach)"),
            "tach check --dependencies --interfaces\nRepo checks failed deterministically",
            StaticInsights(known_flake()),
            "skip deterministic",
            "deterministic",
            id="deterministic-repo-checks",
        ),
        pytest.param(
            make_job("Validate OpenAPI types", failed_step="Check and update OpenAPI types"),
            "OpenAPI types are out of date. To fix, run locally: hogli build:openapi",
            StaticInsights(known_flake()),
            "skip deterministic",
            "deterministic",
            id="deterministic-openapi",
        ),
        pytest.param(
            make_job("Frontend lint", failed_step="Lint with Oxlint"),
            "oxlint found errors",
            StaticInsights(known_flake()),
            "skip deterministic",
            "deterministic",
            id="deterministic-lint",
        ),
        pytest.param(
            make_job("Frontend typescript checks", failed_step="Run typescript with strict"),
            "pnpm --filter=@posthog/frontend typescript:check failed",
            StaticInsights(known_flake()),
            "skip deterministic",
            "deterministic",
            id="deterministic-typescript",
        ),
        pytest.param(
            make_job("Validate migrations", failed_step="Check migrations"),
            "python manage.py makemigrations --check --dry-run failed",
            StaticInsights(known_flake()),
            "skip deterministic",
            "deterministic",
            id="deterministic-migrations",
        ),
        pytest.param(
            make_job("Build and deploy", failed_step="Compile assets"),
            "error: build failed on attempt 1",
            StaticInsights(known_flake()),
            "skip unknown",
            "not an allowlisted test runner",
            id="non-test-job",
        ),
        pytest.param(
            make_job("Django tests - Core (1/1)"),
            "FAILED posthog/test/test_something.py::test_new_regression\nAssertionError: expected 1 == 2",
            StaticInsights(None),
            "skip unknown",
            "no high-confidence known flaky signature matched",
            id="unknown-signature",
        ),
        pytest.param(
            make_job("Django tests - Temporal (1/1)", run_attempt=2),
            "FAILED posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found\nQUERY_WITH_SAME_ID_IS_ALREADY_RUNNING",
            StaticInsights(known_flake()),
            "skip cap reached",
            "automatic rerun cap 1",
            id="rerun-cap-exceeded",
        ),
    ],
)
def test_failures_are_not_rerun(
    job: Job,
    log: str,
    insights: StaticInsights,
    expected_action: str,
    expected_reason_fragment: str,
) -> None:
    decision = classify(job, log, insights)

    assert decision.action == expected_action
    assert expected_reason_fragment in decision.reason


def test_non_test_job_at_attempt_above_cap_reports_test_type_not_cap() -> None:
    decision = classify(
        make_job("Build and deploy", run_attempt=2, failed_step="Compile assets"),
        "error: build failed on attempt 2",
        StaticInsights(known_flake()),
    )

    assert decision.action == "skip unknown"
    assert "not an allowlisted test runner" in decision.reason


def test_prior_same_sha_rerun_cap_is_not_rerun() -> None:
    decision = classify_job(
        make_job("Django tests - Temporal (1/1)"),
        "FAILED posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found\nQUERY_WITH_SAME_ID_IS_ALREADY_RUNNING",
        StaticInsights(known_flake()),
        workflow_name="Backend CI",
        max_reruns_per_job=1,
        get_cap_reached_reason=lambda: "matching job already reached attempt 2 for head SHA abc123",
    )

    assert decision.action == "skip cap reached"
    assert "matching job already reached attempt 2" in decision.reason


@pytest.mark.parametrize(
    ("log", "expected_query"),
    [
        pytest.param(
            "FAILED posthog/test/test_x.py::test_alpha[param]",
            "posthog/test/test_x.py::test_alpha[param]",
            id="pytest-failed-line",
        ),
        pytest.param(
            "  posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found PASSED earlier",
            "posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found",
            id="py-node-id",
        ),
        pytest.param(
            "some prose mentioning test_bare_function in passing",
            "test_bare_function",
            id="bare-test-name",
        ),
        pytest.param(
            "frontend/src/scenes/foo.spec.tsx:12:5 › my flow shows an error",
            "frontend/src/scenes/foo.spec.tsx:12:5 › my flow shows an error",
            id="playwright-spec-line",
        ),
        pytest.param(
            "[chromium] › login flow shows the error banner",
            "login flow shows the error banner",
            id="playwright-project-line",
        ),
        pytest.param(
            "raised QUERY_WITH_SAME_ID_IS_ALREADY_RUNNING during the run",
            "QUERY_WITH_SAME_ID_IS_ALREADY_RUNNING",
            id="screaming-snake-error-code",
        ),
    ],
)
def test_extract_failure_queries_matches_each_pattern(log: str, expected_query: str) -> None:
    assert expected_query in extract_failure_queries(log)


def test_extract_failure_queries_returns_empty_when_no_signature() -> None:
    assert extract_failure_queries("everything is fine, nothing to see here\n") == ()


def test_extract_failure_queries_dedupes_repeated_signatures() -> None:
    log = "FAILED a/b.py::test_x\nFAILED a/b.py::test_x\n"
    queries = extract_failure_queries(log)

    assert queries.count("a/b.py::test_x") == 1


def test_extract_failure_queries_caps_total_count() -> None:
    log = "\n".join(f"FAILED a.py::test_n{i}" for i in range(MAX_QUERY_COUNT + 5))
    queries = extract_failure_queries(log)

    assert len(queries) == MAX_QUERY_COUNT


def test_extract_failure_queries_truncates_long_query() -> None:
    log = "frontend/src/x.spec.tsx:1:1 › " + "a" * 400
    [query] = [q for q in extract_failure_queries(log) if q.startswith("frontend/src/x.spec.tsx")]

    assert len(query) == 220
