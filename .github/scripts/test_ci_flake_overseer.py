from __future__ import annotations

import json

import pytest

import ci_flake_overseer
from ci_flake_overseer import (
    DECISION_EVENT,
    MAX_QUERY_COUNT,
    OUTCOME_EVENT,
    CiInsightsSource,
    Decision,
    FlakeMatch,
    InsightsSource,
    Job,
    JsonObject,
    Step,
    WorkflowRun,
    build_decision_events,
    capture_events,
    classify_job,
    extract_failure_queries,
    is_test_job_failure,
    report_rerun_outcomes,
    rerun_eligible_jobs,
    rerun_outcome_label,
)


class StaticInsights:
    def __init__(self, match: FlakeMatch | None) -> None:
        self.match = match
        self.queries: tuple[str, ...] = ()

    def find_flake(self, queries: tuple[str, ...], workflow_name: str, log: str) -> FlakeMatch | None:
        self.queries = queries
        return self.match


def make_job(
    name: str,
    *,
    run_attempt: int = 1,
    conclusion: str = "failure",
    failed_step: str = "Run Core tests",
) -> Job:
    return Job(
        id=123,
        name=name,
        conclusion=conclusion,
        run_attempt=run_attempt,
        html_url="https://github.com/PostHog/posthog/actions/runs/1/job/123",
        steps=(Step(name=failed_step, conclusion="failure"),),
    )


def known_flake() -> FlakeMatch:
    return FlakeMatch(
        insight_id="01KNOWNFLAKE",
        title="Flaky test: test_acheck_query_found ClickHouse query ID collision",
        confidence=85,
        matched_query="test_acheck_query_found",
        summary="test_acheck_query_found fails intermittently",
    )


def classify(job: Job, log: str, insights: InsightsSource) -> Decision:
    return classify_job(
        job,
        lambda: log,
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
            make_job("Django tests - Core (1/1)", failed_step="Run Core tests"),
            "Core tests failed\nA retry cannot fix this failure",
            StaticInsights(known_flake()),
            "skip deterministic",
            "deterministic",
            id="deterministic-from-log-only",
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
        lambda: (
            "FAILED posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found\nQUERY_WITH_SAME_ID_IS_ALREADY_RUNNING"
        ),
        StaticInsights(known_flake()),
        workflow_name="Backend CI",
        max_reruns_per_job=1,
        get_cap_reached_reason=lambda: "matching job already reached attempt 2 for head SHA abc123",
    )

    assert decision.action == "skip cap reached"
    assert "matching job already reached attempt 2" in decision.reason


def test_job_log_is_not_fetched_for_metadata_only_skips() -> None:
    def explode() -> str:
        raise AssertionError("log should not be fetched for a non-test job")

    decision = classify_job(
        make_job("Build and deploy", failed_step="Compile assets"),
        explode,
        StaticInsights(known_flake()),
        workflow_name="Backend CI",
        max_reruns_per_job=1,
    )

    assert decision.action == "skip unknown"


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


QUERY = "test_acheck_query_found"
MATCH_LOG = "FAILED posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found\n"


def make_insight(**overrides: object) -> JsonObject:
    insight: JsonObject = {
        "id": "01ABC",
        "title": "Flaky test test_acheck_query_found",
        "summary": "fails intermittently with a ClickHouse query id collision",
        "hypothesis_confidence": 90,
        "status": "open",
        "source_ref": {"workflow_name": "Backend CI"},
    }
    insight.update(overrides)
    return insight


def matcher() -> CiInsightsSource:
    return CiInsightsSource(("noop",), 80, 5)


@pytest.mark.parametrize(
    ("overrides", "should_match"),
    [
        pytest.param({"status": "open"}, True, id="status-open"),
        pytest.param({"status": "resolved"}, False, id="status-resolved"),
        pytest.param({"status": "dismissed"}, False, id="status-dismissed"),
        pytest.param({"hypothesis_confidence": 50}, False, id="below-confidence-threshold"),
        pytest.param(
            {"title": "test_acheck_query_found regression", "summary": "a deterministic failure"},
            False,
            id="no-flakiness-keyword",
        ),
        pytest.param({"source_ref": {"workflow_name": "E2E CI Playwright"}}, False, id="workflow-scope-mismatch"),
    ],
)
def test_flake_match_gates(overrides: dict[str, object], should_match: bool) -> None:
    match = matcher().flake_match(make_insight(**overrides), QUERY, "Backend CI", MATCH_LOG)

    assert (match is not None) is should_match


def test_flake_match_returns_insight_details() -> None:
    match = matcher().flake_match(make_insight(), QUERY, "Backend CI", MATCH_LOG)

    assert match is not None
    assert match.insight_id == "01ABC"
    assert match.confidence == 90
    assert match.matched_query == QUERY


def test_flake_match_requires_term_in_both_log_and_insight() -> None:
    assert matcher().flake_match(make_insight(), QUERY, "Backend CI", "unrelated failure output") is None


def test_flake_match_skips_when_no_significant_term() -> None:
    assert matcher().flake_match(make_insight(), "boom", "Backend CI", "boom happened") is None


class FakeCli(CiInsightsSource):
    def __init__(self, search_results: list[JsonObject], views: dict[str, JsonObject]) -> None:
        super().__init__(("noop",), 80, 5)
        self._search_results = search_results
        self._views = views

    def search(self, query: str) -> list[JsonObject]:
        return self._search_results

    def view(self, insight_id: str) -> JsonObject:
        return self._views.get(insight_id, {})


def test_find_flake_skips_insight_with_empty_view() -> None:
    cli = FakeCli([{"id": "01ABC"}], views={})

    assert cli.find_flake((QUERY,), "Backend CI", MATCH_LOG) is None


def test_find_flake_matches_on_detailed_view() -> None:
    cli = FakeCli([{"id": "01ABC"}], views={"01ABC": make_insight()})

    match = cli.find_flake((QUERY,), "Backend CI", MATCH_LOG)

    assert match is not None
    assert match.insight_id == "01ABC"


def make_rerun_decision() -> Decision:
    return Decision(
        action="rerun",
        reason="matched high-confidence known flaky signature",
        job=make_job("Django tests - Temporal (1/1)"),
        match=known_flake(),
    )


def test_rerun_eligible_jobs_calls_api_when_active(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(ci_flake_overseer, "gh_post", lambda repo, path: calls.append(path))

    rerun_eligible_jobs("PostHog/posthog", (make_rerun_decision(),), dry_run=False)

    assert calls == ["actions/jobs/123/rerun"]


def test_rerun_eligible_jobs_skips_api_in_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(ci_flake_overseer, "gh_post", lambda repo, path: calls.append(path))

    rerun_eligible_jobs("PostHog/posthog", (make_rerun_decision(),), dry_run=True)

    assert calls == []


def make_workflow_run(run_attempt: int = 1) -> WorkflowRun:
    return WorkflowRun(
        id=999,
        workflow_id=42,
        name="Backend CI",
        conclusion="failure",
        head_sha="abc123",
        run_attempt=run_attempt,
        html_url="https://github.com/PostHog/posthog/actions/runs/999",
    )


def test_build_decision_events_one_event_per_decision() -> None:
    decisions = (
        make_rerun_decision(),
        Decision(action="skip unknown", reason="no signature", job=make_job("Django tests - Core (1/1)")),
    )

    events = build_decision_events(
        "PostHog/posthog", make_workflow_run(), decisions, dry_run=True, enabled=False, reran_job_ids=set()
    )

    assert [event["event"] for event in events] == [DECISION_EVENT, DECISION_EVENT]
    assert all(event["distinct_id"] == "PostHog/posthog" for event in events)
    first = events[0]["properties"]
    assert first["action"] == "rerun"
    assert first["workflow_name"] == "Backend CI"
    assert first["dry_run"] is True
    assert first["reran"] is False
    assert first["insight_id"] == "01KNOWNFLAKE"
    assert first["$groups"] == {"workflow_run": "999"}


def test_build_decision_events_marks_reran_jobs() -> None:
    [event] = build_decision_events(
        "PostHog/posthog",
        make_workflow_run(),
        (make_rerun_decision(),),
        dry_run=False,
        enabled=True,
        reran_job_ids={123},
    )

    assert event["properties"]["reran"] is True
    assert event["properties"]["enabled"] is True


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
    events = report_rerun_outcomes(
        "PostHog/posthog",
        make_workflow_run(run_attempt=1),
        StaticInsights(known_flake()),
        1,
        dry_run=True,
        enabled=False,
    )

    assert events == []


@pytest.mark.parametrize(
    ("current_conclusion", "expected_outcome"),
    [
        pytest.param("success", "cleared", id="rerun-cleared"),
        pytest.param("failure", "still_failing", id="rerun-still-failing"),
        pytest.param("timed_out", "still_failing", id="rerun-timed-out"),
    ],
)
def test_report_rerun_outcomes_attributes_prior_rerun(
    monkeypatch: pytest.MonkeyPatch, current_conclusion: str, expected_outcome: str
) -> None:
    job_name = "Django tests - Temporal (1/1)"

    def fake_fetch_jobs(repo: str, run_id: int, attempt: int) -> tuple[Job, ...]:
        if attempt == 1:
            return (make_job(job_name, conclusion="failure"),)
        return (make_job(job_name, conclusion=current_conclusion),)

    monkeypatch.setattr(ci_flake_overseer, "fetch_jobs", fake_fetch_jobs)
    monkeypatch.setattr(
        ci_flake_overseer,
        "gh_text",
        lambda repo, path: "FAILED posthog/temporal/tests/test_clickhouse.py::test_acheck_query_found\n",
    )

    events = report_rerun_outcomes(
        "PostHog/posthog",
        make_workflow_run(run_attempt=2),
        StaticInsights(known_flake()),
        1,
        dry_run=True,
        enabled=False,
    )

    assert len(events) == 1
    assert events[0]["event"] == OUTCOME_EVENT
    props = events[0]["properties"]
    assert props["outcome"] == expected_outcome
    assert props["job_name"] == job_name
    assert props["prior_attempt"] == 1
    assert props["attempt"] == 2
    assert props["insight_id"] == "01KNOWNFLAKE"


def test_report_rerun_outcomes_ignores_non_eligible_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch_jobs(repo: str, run_id: int, attempt: int) -> tuple[Job, ...]:
        return (make_job("Build and deploy", conclusion="failure", failed_step="Compile assets"),)

    monkeypatch.setattr(ci_flake_overseer, "fetch_jobs", fake_fetch_jobs)
    monkeypatch.setattr(ci_flake_overseer, "gh_text", lambda repo, path: "build failed")

    events = report_rerun_outcomes(
        "PostHog/posthog",
        make_workflow_run(run_attempt=2),
        StaticInsights(known_flake()),
        1,
        dry_run=True,
        enabled=False,
    )

    assert events == []


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
