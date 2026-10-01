from __future__ import annotations

from datetime import date
from typing import Any

from parameterized import parameterized
from same_commit_flakes import (
    MAX_DISAGREEMENTS_PER_COMMIT,
    SUITES,
    Disagreement,
    Finding,
    Report,
    Run,
    Trial,
    Verdict,
    classify,
    comparable_runs,
    compare,
    quarantine_core,
    render_annotations,
    render_summary,
)

REPO = "PostHog/posthog"
SHA = "c0ffee0000000000000000000000000000000001"
FRONTEND = SUITES[".github/workflows/ci-frontend.yml"]
THREAD_TEST = "frontend/src/scenes/max/maxThreadLogic.test.ts::maxThreadLogic error tracking capture gating reports a server failure"
SIBLING_TEST = "frontend/src/scenes/max/maxThreadLogic.test.ts::maxThreadLogic streams a reply"

PUSH = Run(id=101, event="push", head_sha=SHA, html_url="https://github.com/PostHog/posthog/actions/runs/101")
HOURLY = Run(id=202, event="schedule", head_sha=SHA, html_url="https://github.com/PostHog/posthog/actions/runs/202")
HOURLY_RERUN = Run(
    id=303, event="schedule", head_sha=SHA, html_url="https://github.com/PostHog/posthog/actions/runs/303", attempts=2
)


def junit_case(name: str, *children: str, file: str = "src/scenes/max/maxThreadLogic.test.ts") -> str:
    full_name = f"maxThreadLogic {name}"
    body = "".join(f"<{child}>expected 1 call, received 3</{child}>" for child in children)
    return f'<testcase classname="{full_name}" name="{full_name}" time="0.4" file="{file}">{body}</testcase>'


def junit(*testcases: str) -> bytes:
    return f'<testsuites><testsuite name="suite">{"".join(testcases)}</testsuite></testsuites>'.encode()


PASSING = junit(junit_case("error tracking capture gating reports a server failure"), junit_case("streams a reply"))
FAILING = junit(
    junit_case("error tracking capture gating reports a server failure", "rerunFailure", "failure"),
    junit_case("streams a reply"),
)


class FakeGitHub:
    def __init__(self, artifacts_by_run: dict[Run, dict[str, bytes]]) -> None:
        self._runs = list(artifacts_by_run)
        self._documents: dict[int, bytes] = {}
        self._artifacts: dict[int, list[dict[str, Any]]] = {}
        for run, artifacts in artifacts_by_run.items():
            for name, document in artifacts.items():
                artifact_id = len(self._documents) + 1
                self._documents[artifact_id] = document
                self._artifacts.setdefault(run.id, []).append({"id": artifact_id, "name": name, "expired": False})

    def runs_for_commit(self, workflow_path: str, head_sha: str) -> list[dict[str, Any]]:
        return [run_payload(id=r.id, event=r.event, html_url=r.html_url, run_attempt=r.attempts) for r in self._runs]

    def artifacts(self, run_id: int) -> list[dict[str, Any]]:
        return self._artifacts.get(run_id, [])

    def junit_documents(self, artifact_id: int) -> list[bytes]:
        return [self._documents[artifact_id]]


def compare_runs(artifacts_by_run: dict[Run, dict[str, bytes]]) -> Report:
    return compare(FakeGitHub(artifacts_by_run), FRONTEND, ".github/workflows/ci-frontend.yml", SHA, REPO)


def disagreements_for(artifacts_by_run: dict[Run, dict[str, bytes]]) -> list[Disagreement]:
    return [finding.disagreement for finding in compare_runs(artifacts_by_run).findings]


def run_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "id": 1,
        "event": "schedule",
        "head_sha": SHA,
        "head_branch": "master",
        "head_repository": {"full_name": REPO},
        "status": "completed",
        "conclusion": "failure",
        "html_url": "https://github.com/PostHog/posthog/actions/runs/1",
    }
    return {**payload, **overrides}


@parameterized.expand(
    [
        ("scheduled failure", {}, True),
        ("push success", {"event": "push", "conclusion": "success"}, True),
        ("cancelled", {"conclusion": "cancelled"}, False),
        ("still running", {"status": "in_progress", "conclusion": None}, False),
        ("merge queue branch", {"event": "pull_request", "head_branch": "trunk-merge/pr-1/abc"}, False),
        (
            "fork branch named master",
            {"event": "pull_request", "head_repository": {"full_name": "someone/posthog"}},
            False,
        ),
        ("another commit", {"head_sha": "f" * 40}, False),
    ]
)
def test_comparable_runs_keeps_only_completed_master_runs_of_the_commit(
    _name: str, overrides: dict[str, Any], kept: bool
) -> None:
    assert bool(comparable_runs([run_payload(**overrides)], SHA, REPO)) is kept


def test_a_push_pass_and_an_hourly_failure_on_one_commit_is_a_flake_despite_an_unreadable_shard() -> None:
    report = compare_runs(
        {
            PUSH: {"junit-results-frontend-app-1": PASSING},
            HOURLY: {"junit-results-frontend-app-1": FAILING, "junit-results-frontend-app-2": b"<testsuites"},
        }
    )
    found = [finding.disagreement for finding in report.findings]

    assert [(d.job_key, d.test_id, d.failed_in, d.passed_in) for d in found] == [
        ("junit-results-frontend-app-1", THREAD_TEST, (Trial(HOURLY, 1),), (Trial(PUSH, 1),))
    ]
    assert found[0].test_file == "frontend/src/scenes/max/maxThreadLogic.test.ts"
    assert [skipped.split(":")[0] for skipped in report.skipped_artifacts] == [
        "junit-results-frontend-app-2 of run 202"
    ]


def test_a_single_run_whose_rerun_attempt_passes_is_a_flake() -> None:
    found = disagreements_for(
        {HOURLY_RERUN: {"junit-results-frontend-app-1": FAILING, "junit-results-frontend-app-1-attempt2": PASSING}}
    )

    assert [(d.test_id, d.failed_in, d.passed_in) for d in found] == [
        (THREAD_TEST, (Trial(HOURLY_RERUN, 1),), (Trial(HOURLY_RERUN, 2),))
    ]


def shard_break() -> bytes:
    broken = [junit_case(f"broken {i}", "failure") for i in range(11)]
    return junit(*broken, junit_case("error tracking capture gating reports a server failure", "failure"))


@parameterized.expand(
    [
        ("failed in both runs", FAILING, FAILING, "junit-results-frontend-app-1"),
        ("passed in a different shard", FAILING, PASSING, "junit-results-frontend-app-2"),
        ("failure inside a shard that broke as a whole", shard_break(), PASSING, "junit-results-frontend-app-1"),
        (
            "skipped where the other run passed",
            junit(junit_case("error tracking capture gating reports a server failure", "skipped")),
            PASSING,
            "junit-results-frontend-app-1",
        ),
    ]
)
def test_no_flake_without_a_same_job_disagreement(
    _name: str, hourly_document: bytes, push_document: bytes, push_job: str
) -> None:
    found = disagreements_for(
        {
            PUSH: {push_job: push_document},
            HOURLY: {"junit-results-frontend-app-1": hourly_document},
        }
    )

    assert [d.test_id for d in found] == []


def disagreement(test_id: str = THREAD_TEST) -> Disagreement:
    return Disagreement(
        job_key="junit-results-frontend-app-1",
        test_id=test_id,
        test_file=test_id.split("::")[0],
        failed_in=(Trial(HOURLY, 1),),
        passed_in=(Trial(PUSH, 1),),
    )


def entry(selector: str) -> quarantine_core.Entry:
    return quarantine_core.Entry(
        id=selector, added=date(2026, 9, 30), expires=date(2026, 10, 14), runner="jest", reason="flaky", owner="@x"
    )


@parameterized.expand(
    [
        ("not quarantined", [], Verdict.QUARANTINE_CANDIDATE),
        (
            "file already quarantined",
            [entry("frontend/src/scenes/max/maxThreadLogic.test.ts")],
            Verdict.ALREADY_QUARANTINED,
        ),
    ]
)
def test_classify_marks_tests_the_quarantine_file_already_covers(
    _name: str, active_entries: list[quarantine_core.Entry], expected: Verdict
) -> None:
    assert classify([disagreement()], active_entries) == [expected]


def test_classify_blames_no_test_when_a_commit_disagrees_on_too_many() -> None:
    many = [disagreement(f"{SIBLING_TEST} {i}") for i in range(MAX_DISAGREEMENTS_PER_COMMIT + 1)]

    assert set(classify(many, [])) == {Verdict.SYSTEMIC}


def test_report_names_the_flake_and_flags_an_incomplete_comparison() -> None:
    finding = Finding(disagreement=disagreement(), verdict=Verdict.QUARANTINE_CANDIDATE, owner="@PostHog/team-x")
    report = Report(head_sha=SHA, run_count=2, findings=[finding], skipped_artifacts=["junit-results-frontend-app-2"])

    annotation, incomplete = render_annotations(report)
    summary = render_summary(report)

    assert annotation.startswith("::warning title=Flaky test on master::")
    assert incomplete.startswith("::warning title=Incomplete flake comparison::")
    assert "\n" not in annotation + incomplete
    assert "Comparison incomplete" in summary and "junit-results-frontend-app-2" in summary
    for text in (summary, annotation):
        for expected in (
            THREAD_TEST,
            "junit-results-frontend-app-1",
            "@PostHog/team-x",
            PUSH.html_url,
            HOURLY.html_url,
        ):
            assert expected in text
