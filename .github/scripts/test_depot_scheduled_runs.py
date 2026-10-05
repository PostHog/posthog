import json
import subprocess
from typing import Any

import pytest

import ci_backend_relay
import depot_scheduled_runs as script


@pytest.mark.parametrize(
    "workflow_status,gate_status,expected",
    [
        pytest.param("finished", "finished", ("completed", "success"), id="green"),
        pytest.param("failed", "failed", ("completed", "failure"), id="gate_failed"),
        pytest.param("failed", "finished", ("completed", "success"), id="non_gating_job_failed"),
        pytest.param("running", "finished", ("completed", "success"), id="gate_done_tail_jobs_running"),
        pytest.param("running", "queued", ("in_progress", None), id="still_running"),
        pytest.param("failed", None, ("completed", "failure"), id="failed_before_the_gate"),
        pytest.param("failed", "skipped", ("completed", "failure"), id="gate_skipped_after_a_failure"),
        pytest.param("finished", "skipped", ("completed", "failure"), id="ran_no_tests"),
        pytest.param("cancelled", "cancelled", ("completed", "cancelled"), id="cancelled"),
    ],
)
def test_gate_run_reports_the_gate_verdict(
    monkeypatch: pytest.MonkeyPatch, workflow_status: str, gate_status: str | None, expected: tuple[str, str | None]
) -> None:
    jobs: list[dict[str, Any]] = [{"job_key": "ci-backend.yml:report-test-timings", "status": "failed"}]
    if gate_status:
        jobs.append({"job_key": script.GATE_JOB_KEY, "status": gate_status, "finished_at": "2026-10-05T13:00:00Z"})
    shown = {"org_id": "org", "jobs": jobs}
    monkeypatch.setattr(script, "depot", lambda *args: json.dumps(shown))
    listed = {
        "workflow_id": "wf",
        "run_id": "run",
        "sha": "abc",
        "status": workflow_status,
        "created_at": "2026-10-05T12:23:00Z",
    }

    run = script.gate_run(listed)

    assert (run["status"], run["conclusion"]) == expected
    assert run["head_sha"] == "abc"


def test_names_the_workflow_and_gate_job_the_relay_reads() -> None:
    assert script.WORKFLOW_NAME == ci_backend_relay.DEPOT_WORKFLOW
    assert script.GATE_JOB_KEY == ci_backend_relay.GATE_JOB_KEY


def test_retries_a_workflow_listing_timeout_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def depot_response(*args: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired("depot", script.CLI_TIMEOUT_SECONDS)
        return "[]"

    monkeypatch.setattr(script, "depot", depot_response)

    assert script.scheduled_workflows(["finished"], 5) == []
    assert calls == 2


@pytest.mark.parametrize("status", [None, "running", "cancelled", "finished", "failed"])
def test_gate_window_requires_a_settled_verdict(monkeypatch: pytest.MonkeyPatch, status: str | None) -> None:
    def depot_response(*args: str) -> str:
        if args[:2] == ("workflow", "list"):
            return json.dumps(
                [
                    {
                        "workflow_id": "wf",
                        "run_id": "run",
                        "sha": "abc",
                        "status": status,
                        "created_at": "2026-10-05T12:23:00Z",
                    }
                ]
                if status
                else []
            )
        return json.dumps({"org_id": "org", "jobs": [{"job_key": script.GATE_JOB_KEY, "status": status}]})

    monkeypatch.setattr(script, "depot", depot_response)

    if status in ("finished", "failed"):
        assert script.gate_runs()[0]["conclusion"] == script.GATE_CONCLUSIONS[status]
    else:
        with pytest.raises(ValueError, match="No settled Backend CI verdict"):
            script.gate_runs()


def test_download_keeps_the_newest_artifact_per_name() -> None:
    artifacts = [
        {"name": "timing_data-Core-1", "artifact_id": "retry", "created_at": "2026-10-05T12:40:00Z"},
        {"name": "timing_data-Core-1", "artifact_id": "first", "created_at": "2026-10-05T12:30:00Z"},
        {"name": "timing_data-Core-2", "artifact_id": "only", "created_at": "2026-10-05T12:31:00Z"},
    ]

    assert sorted(a["artifact_id"] for a in script.newest_per_name(artifacts)) == ["only", "retry"]
