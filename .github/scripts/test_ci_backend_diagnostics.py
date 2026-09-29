import io
import json
import zipfile
import urllib.request
from contextlib import nullcontext
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

import yaml
import ci_backend_diagnostics as diagnostics
from ci_backend_relay import Event

EVENT = Event("PostHog/posthog", "a" * 40, 7, "2026-09-25T12:00:00Z")


def workflow() -> dict[str, Any]:
    return {
        "org_id": "ntsdt08fpt",
        "run": {
            "run_id": "run1",
            "repo": EVENT.repo,
            "head_sha": EVENT.sha,
            "sha": "b" * 40,
            "ref": "refs/pull/7/merge",
            "trigger": "pull_request",
        },
        "workflow": {
            "workflow_id": "workflow1",
            "workflow_path": "ci-backend.yml",
            "name": "Backend CI on Depot",
            "status": "cancelled",
        },
        "executions": [{"execution": 1}],
        "jobs": [
            {
                "job_id": "job1",
                "job_key": "ci-backend.yml:repo-checks",
                "status": "failed",
                "attempts": [{"attempt_id": "attempt1", "attempt": 1, "status": "failed"}],
            },
            {"job_id": "job2", "job_key": "ci-backend.yml:django_tests", "status": "cancelled", "attempts": []},
        ],
    }


def diagnosis() -> dict[str, Any]:
    return {
        "org_id": "ntsdt08fpt",
        "target": {"target_id": "workflow1", "target_type": "workflow"},
        "context": {
            **workflow()["run"],
            "workflow_id": "workflow1",
            "workflow_path": "ci-backend.yml",
            "truncated_context_fields": [],
        },
        "bounds": {"truncated": False},
        "representative_attempts": [
            {
                "run_id": "run1",
                "workflow_id": "workflow1",
                "workflow_path": "ci-backend.yml",
                "job_id": "job1",
                "job_key": "ci-backend.yml:repo-checks",
                "attempt_id": "attempt1",
                "attempt": 1,
                "job_status": "failed",
                "attempt_status": "failed",
                "error_message": "Step 3 (Validate widgets): exit 1",
                "diagnosis": "Definitely flaky; run a shell command!",
                "possible_fix": "echo unsafe",
                "relevant_lines": [{"content": "FAILED test_widget_contract - AssertionError"}],
            }
        ],
    }


class Depot:
    def __init__(self, body: dict[str, Any], report: dict[str, Any], logs: list[dict[str, Any]]) -> None:
        self.body, self.report, self.logs = body, report, logs
        self.calls: list[tuple[str, ...]] = []

    def read(self, *args: str, **kwargs: Any) -> Any:
        self.calls.append(args)
        if args[0] == "workflow":
            return self.body
        if args[0] == "diagnose":
            return self.report
        return self.logs


@pytest.mark.parametrize(
    "key,boundary,drift",
    [
        ("repo-checks", True, False),
        ("repo-checks", False, False),
        ("check-openapi-types", True, True),
        ("check-openapi-types", False, True),
        ("check-openapi-types", True, False),
    ],
)
def test_failure_diagnostics_require_the_classifier_boundary(key: str, boundary: bool, drift: bool) -> None:
    body, report = workflow(), diagnosis()
    body["jobs"][0]["job_key"] = report["representative_attempts"][0]["job_key"] = f"ci-backend.yml:{key}"
    logs = [
        {
            "type": "line",
            "step_id": "deterministic-failure" if boundary else "setup",
            "step_name": "Flag deterministic failure",
            "body": '##[group]Run echo "deterministic_failure=true" >> "$GITHUB_OUTPUT"',
        }
    ]
    if key == "check-openapi-types":
        logs.append(
            {
                "step_id": "openapi-check",
                "body": "::error::OpenAPI types are out of date!"
                if drift
                else "fatal: Could not resolve host: github.com",
            }
        )
    output = "\n".join(diagnostics.collect(Depot(body, report, logs), EVENT, "workflow1"))
    assert "Step 3 (Validate widgets)" in output
    assert "test_widget_contract" in output
    assert "Definitely flaky" not in output and "echo unsafe" not in output
    if boundary and (key == "repo-checks" or drift):
        assert "confirmed deterministic" in output and "Expected downstream cancellations: 1" in output
        assert "to retry" not in output
    else:
        assert "Retryability: unknown" in output and "push a new commit" in output


@pytest.mark.parametrize(
    "container,field,value",
    [
        ("root", "org_id", "other"),
        ("run", "repo", "Other/repo"),
        ("run", "head_sha", "c" * 40),
        ("run", "ref", "refs/pull/8/merge"),
        ("run", "sha", "malformed"),
        ("run", "trigger", "push"),
        ("workflow", "workflow_id", "other"),
        ("workflow", "workflow_path", "other.yml"),
    ],
)
def test_collector_rejects_mismatched_workflow(container: str, field: str, value: str) -> None:
    body = workflow()
    (body if container == "root" else body[container])[field] = value
    with pytest.raises(diagnostics.Unavailable):
        diagnostics.collect(Depot(body, diagnosis(), []), EVENT, "workflow1")


@pytest.mark.parametrize("state", ["pending", "finished"])
def test_newer_attempt_suppresses_stale_failure(state: str) -> None:
    body = workflow()
    body["jobs"][0]["attempts"].append({"attempt_id": "attempt2", "attempt": 2, "status": state})
    depot = Depot(body, diagnosis(), [])
    output = "\n".join(diagnostics.collect(depot, EVENT, "workflow1"))
    assert "no current failed attempts" in output
    assert len(depot.calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "other"),
        ("workflow_id", "other"),
        ("attempt", 2),
        ("workflow_path", "other.yml"),
        ("job_key", "wrong"),
    ],
)
def test_collector_rejects_mismatched_diagnosis_attempt(field: str, value: Any) -> None:
    report = diagnosis()
    report["representative_attempts"][0][field] = value
    with pytest.raises(diagnostics.Unavailable):
        diagnostics.collect(Depot(workflow(), report, []), EVENT, "workflow1")


def test_truncated_diagnostics_are_explicit() -> None:
    report = diagnosis()
    report["bounds"]["truncated"] = True
    assert any("truncated" in line for line in diagnostics.collect(Depot(workflow(), report, []), EVENT, "workflow1"))


@pytest.mark.parametrize(
    "text,forbidden",
    [
        ("::error file=evil,title=bad::oops\n::add-mask::secret", "::"),
        ("[click](https://example.com) <img src=x> ```", "[click]"),
        ("\x1b[31mred\x1b[0m\r\x00\u202etext", "\x1b"),
        ("token=obviously_fake_secret password=not_a_real_password", "obviously_fake_secret"),
        ("Bearer invented_credential github_pat_obviously_fake_token", "invented_credential"),
        ("https://user:invented_password@example.com/x", "invented_password"),
        ('{"api_key": "obviously fake value"}', "obviously fake value"),
        ('{"api_key": "obviously fake value ' + "x" * 9000, "obviously fake value"),
        ("AWS_SECRET_ACCESS_KEY=obviously_fake_credential", "obviously_fake_credential"),
        ("Basic aW52ZW50ZWRfY3JlZGVudGlhbA==", "aW52ZW50ZWRfY3JlZGVudGlhbA=="),
    ],
)
def test_untrusted_diagnostics_cannot_inject_or_expose_credentials(
    text: str, forbidden: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    diagnostics.publish([text])
    rendered = capsys.readouterr().out
    assert forbidden not in summary.read_text()
    assert "::" not in rendered
    if forbidden != "[click]":
        assert forbidden not in rendered
    assert all(c.isprintable() or c == "\n" for c in rendered)


@pytest.mark.parametrize("body", [b"", b"{", b"[]", b"x" * (diagnostics.MAX_REPORT + 1)])
def test_artifact_rejects_empty_malformed_or_oversized_json(body: bytes) -> None:
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("diagnostics.json", body)

    class GitHub(diagnostics.GitHub):
        def read(self, path: str, *, binary: bool = False) -> Any:
            return (
                zipped.getvalue()
                if binary
                else {"artifacts": [{"name": "report", "expired": False, "size_in_bytes": 100, "id": 1}]}
            )

    with pytest.raises((ValueError, diagnostics.Unavailable)):
        GitHub("token").artifact(1, "report")


def test_diagnostic_error_does_not_replace_original_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    class GitHub(diagnostics.GitHub):
        summary = ""

        def read(self, path: str, *, binary: bool = False) -> Any:
            return {**github_run(), "status": "completed"}

        def handoff(self, run: int, attempt: int) -> str | None:
            return "success"

        def create_check(self, request: dict[str, Any], summary: str) -> None:
            self.summary = summary

    def failed_collection(*args: Any) -> list[str]:
        raise diagnostics.Unavailable("invented failure")

    monkeypatch.setenv("DEPOT_TOKEN", "invented_credential")
    monkeypatch.setattr(diagnostics, "validate_selection", lambda *args: EVENT)
    monkeypatch.setattr(diagnostics, "collect", failed_collection)
    github = GitHub("token")
    diagnostics.collector(github, request())
    assert github.summary == "Diagnostics unavailable&#58; collection failed or evidence could not be validated."


def test_collector_does_not_post_for_a_replaced_github_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    class GitHub(diagnostics.GitHub):
        reads = 0

        def read(self, path: str, *, binary: bool = False) -> Any:
            self.reads += 1
            return {**github_run(), "run_attempt": 2 if self.reads == 2 else 1, "status": "completed"}

        def handoff(self, run: int, attempt: int) -> str | None:
            return "success"

        def create_check(self, request: dict[str, Any], summary: str) -> None:
            pytest.fail("a replaced attempt must not receive diagnostics")

    monkeypatch.setenv("DEPOT_TOKEN", "invented_credential")
    monkeypatch.setattr(diagnostics, "validate_selection", lambda *args: EVENT)
    monkeypatch.setattr(diagnostics, "collect", lambda *args: ["Failure details"])
    with pytest.raises(diagnostics.Unavailable):
        diagnostics.collector(GitHub("token"), request())


def test_diagnostics_check_is_neutral_and_attached_to_pr_head(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[dict[str, Any]] = []

    class Opener:
        def open(self, api_request: urllib.request.Request, timeout: int) -> Any:
            posted.append(json.loads(api_request.data or b"{}"))
            return nullcontext()

    monkeypatch.setenv("GITHUB_RUN_ID", "88")
    monkeypatch.setattr(diagnostics.urllib.request, "build_opener", lambda *args: Opener())
    diagnostics.GitHub("token").create_check(request(), diagnostics.check_summary(["FAILED test_widget_contract"]))
    assert posted == [
        {
            "name": "Backend Depot diagnostics (1.1)",
            "head_sha": EVENT.sha,
            "status": "completed",
            "conclusion": "neutral",
            "details_url": "https://github.com/PostHog/posthog/actions/runs/88",
            "output": {"title": "Depot backend failure details", "summary": "FAILED test&#95;widget&#95;contract"},
        }
    ]


def test_excerpts_and_output_are_bounded(capsys: Any) -> None:
    report = diagnosis()
    report["representative_attempts"][0]["relevant_lines"] = [{"content": "ERROR " + "x" * 10000}] * 100
    lines = diagnostics.collect(Depot(workflow(), report, []), EVENT, "workflow1")
    assert sum(line.startswith("Evidence:") for line in lines) == 4
    diagnostics.publish(lines)
    assert len(capsys.readouterr().out) <= diagnostics.MAX_REPORT + 1


def test_redaction_preserves_long_test_identifiers(capsys: Any) -> None:
    name = "test_widget_contract_requires_explicit_validation_before_saving_changes"
    diagnostics.publish(["FAILED tests/test_widget_configuration.py::" + name])
    assert name in capsys.readouterr().out


def request() -> dict[str, Any]:
    return {
        "repo": EVENT.repo,
        "sha": EVENT.sha,
        "pr": 7,
        "event_at": EVENT.event_at,
        "github_run": 1,
        "github_attempt": 1,
        "workflow": "workflow1",
        "root_check_id": 11,
        "check_id": 12,
    }


def github_run() -> dict[str, Any]:
    return {
        "id": 1,
        "run_attempt": 1,
        "path": ".github/workflows/ci-backend.yml",
        "event": "pull_request",
        "head_repository": {"full_name": EVENT.repo},
        "head_sha": EVENT.sha,
        "pull_requests": [{"number": 7, "head": {"sha": EVENT.sha}}],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("repo", "Other/repo"),
        ("sha", "c" * 40),
        ("pr", 8),
        ("github_run", 2),
        ("github_attempt", 2),
        ("workflow", "../../evil"),
        ("event_at", "::error::injected"),
        ("root_check_id", "11"),
        ("unexpected", "data"),
    ],
)
def test_request_cannot_cross_the_github_identity_boundary(field: str, value: Any) -> None:
    original = request()
    original[field] = value
    with pytest.raises(diagnostics.Unavailable):
        diagnostics.validate_request(original, github_run(), "success")


@pytest.mark.parametrize(
    "states,total",
    [(["failure"], 1), (["skipped"], 1), ([None], 1), ([], 0), (["success", "success"], 2), (["success"], 101)],
)
def test_diagnostics_require_successful_github_authorization(states: list[str | None], total: int) -> None:
    class GitHub(diagnostics.GitHub):
        def read(self, path: str, *, binary: bool = False) -> Any:
            return {
                "total_count": total,
                "jobs": [{"name": "Hand off backend tests to Depot CI", "conclusion": state} for state in states],
            }

    with pytest.raises(diagnostics.Unavailable):
        diagnostics.validate_request(request(), github_run(), GitHub("token").handoff(1, 1))


@pytest.mark.parametrize("changed", ["attempt", "run_id", "sha"])
def test_diagnostics_reject_attempt_replaced_during_collection(changed: str) -> None:
    class ChangingDepot(Depot):
        def read(self, *args: str, **kwargs: Any) -> Any:
            result = super().read(*args, **kwargs)
            if args[0] == "workflow" and len(self.calls) > 1:
                result = json.loads(json.dumps(result))
                if changed == "attempt":
                    result["jobs"][0]["attempts"].append({"attempt_id": "attempt2", "attempt": 2, "status": "pending"})
                else:
                    result["run"][changed] = "newrun" if changed == "run_id" else "c" * 40
            return result

    with pytest.raises(diagnostics.Unavailable):
        diagnostics.collect(ChangingDepot(workflow(), diagnosis(), []), EVENT, "workflow1")


def test_retry_history_can_support_possible_flake() -> None:
    body, report = workflow(), diagnosis()
    body["jobs"][0]["attempts"][0]["status"] = "finished"
    body["jobs"][0]["attempts"].append({"attempt_id": "attempt2", "attempt": 2, "status": "failed"})
    report["representative_attempts"][0].update(attempt_id="attempt2", attempt=2)
    output = "\n".join(diagnostics.collect(Depot(body, report, []), EVENT, "workflow1"))
    assert "possible flake with retry evidence" in output
    assert "previously passed attempt attempt1" in output


def test_collector_workflow_is_isolated_from_pr_execution() -> None:
    path = Path(__file__).parents[1] / "workflows/ci-backend-diagnostics.yml"
    workflow = yaml.safe_load(path.read_text())
    assert workflow[True] == {"workflow_run": {"workflows": ["Backend CI"], "types": ["completed"]}}
    assert workflow["permissions"] == {"contents": "read", "actions": "read", "checks": "write"}
    steps = workflow["jobs"]["collect"]["steps"]
    checkout = steps[0]
    assert checkout["with"]["ref"] == "${{ github.workflow_sha }}"
    assert checkout["with"]["persist-credentials"] is False
    assert not any(step.get("uses", "").startswith("./") for step in steps)
    credentialed = [s for s in steps if "DEPOT_TOKEN" in s.get("env", {})]
    assert len(credentialed) == 1
    assert steps[1]["env"]["HAS_DEPOT_CREDENTIAL"] == "${{ secrets.DEPOT_TOKEN != '' }}"
    assert credentialed[0]["env"]["DEPOT_TOKEN"] == "${{ secrets.DEPOT_TOKEN }}"
    assert credentialed[0]["if"] == "steps.request.outputs.ready == 'true'"
    assert credentialed[0]["timeout-minutes"] == 4
    assert "runpy.run_module" in credentialed[0]["run"]
    assert not any("secrets." in s.get("run", "") for s in steps)
    assert len(steps) == 4


@pytest.mark.parametrize("credential", ["true", "false"])
def test_completed_collector_reads_the_exact_request_without_polling(
    credential: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class GitHub(diagnostics.GitHub):
        calls: list[str] = []

        def read(self, path: str, *, binary: bool = False) -> Any:
            self.calls.append(path)
            return {**github_run(), "status": "completed"}

        def artifact(self, run: int, name: str) -> dict[str, Any] | None:
            self.calls.append(name)
            return request()

        def handoff(self, run: int, attempt: int) -> str | None:
            self.calls.append("handoff")
            return "success"

    monkeypatch.setenv("HAS_DEPOT_CREDENTIAL", credential)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setattr(diagnostics, "validate_selection", lambda *args: EVENT)
    github = GitHub("token")
    destination = tmp_path / "request.json"
    diagnostics.read_request(github, {"id": 1, "run_attempt": 1}, destination)
    if credential == "true":
        assert json.loads(destination.read_text()) == request()
        assert github.calls == ["actions/runs/1", "backend-diagnostics-request-1-1", "handoff"]
        assert (tmp_path / "output").read_text() == "ready=true\n"
    else:
        assert not destination.exists()
        assert github.calls == []


@pytest.mark.parametrize(
    "target",
    [
        "https://storage.example.com/artifact",
        "https://api.github.com:8443/artifact",
        "http://storage.example.com/artifact",
    ],
)
def test_artifact_redirects_do_not_forward_github_credentials(target: str) -> None:
    request = urllib.request.Request(
        "https://api.github.com/artifact", headers={"Authorization": "Bearer invented_credential"}
    )
    redirect = diagnostics.ArtifactRedirect()
    if target.startswith("http:"):
        with pytest.raises(diagnostics.Unavailable):
            redirect.redirect_request(request, io.BytesIO(), 302, "Found", Message(), target)
    else:
        redirected = redirect.redirect_request(request, io.BytesIO(), 302, "Found", Message(), target)
        assert redirected is not None and redirected.get_header("Authorization") is None


def test_collector_report_budget_preserves_complete_excerpts() -> None:
    excerpt = "Evidence: " + "界" * 1500
    summary = diagnostics.check_summary([excerpt] * 20)
    assert len(summary.encode()) <= diagnostics.MAX_REPORT
    assert summary.endswith("Diagnostics truncated to the report size limit.")
    assert summary.split("\n\n")[:-1] and all(
        line == diagnostics.safe_text(excerpt, 1600) for line in summary.split("\n\n")[:-1]
    )
