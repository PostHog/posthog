import json
import importlib.util
from pathlib import Path
from typing import Any

import pytest

import ci_backend_relay

SCRIPT_PATH = Path(__file__).with_name("depot_scheduled_runs.py")
SPEC = importlib.util.spec_from_file_location("depot_scheduled_runs", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)


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


def test_download_keeps_the_newest_artifact_per_name() -> None:
    artifacts = [
        {"name": "timing_data-Core-1", "artifact_id": "retry", "created_at": "2026-10-05T12:40:00Z"},
        {"name": "timing_data-Core-1", "artifact_id": "first", "created_at": "2026-10-05T12:30:00Z"},
        {"name": "timing_data-Core-2", "artifact_id": "only", "created_at": "2026-10-05T12:31:00Z"},
    ]

    assert sorted(a["artifact_id"] for a in script.newest_per_name(artifacts)) == ["only", "retry"]
