import re
import json
import zipfile
import subprocess
from pathlib import Path
from typing import Any

import pytest

import depot_backend_runs as script

MASTER_SHA = "a" * 40
BRANCH_SHA = "b" * 40


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


@pytest.mark.parametrize(
    "trigger,sha,kept",
    [("push", MASTER_SHA, 1), ("push", BRANCH_SHA, 0), ("schedule", BRANCH_SHA, 1)],
    ids=["master", "branch", "schedule"],
)
def test_gate_runs_drop_runs_from_other_branches(
    monkeypatch: pytest.MonkeyPatch, trigger: str, sha: str, kept: int
) -> None:
    def depot_response(*args: str) -> str:
        if args[:2] == ("workflow", "list"):
            return json.dumps(
                [
                    {
                        "workflow_id": "wf",
                        "run_id": "run",
                        "sha": sha,
                        "status": "finished",
                        "created_at": "2026-10-05T12:23:00Z",
                    }
                ]
            )
        return json.dumps({"org_id": "org", "jobs": [{"job_key": script.GATE_JOB_KEY, "status": "finished"}]})

    monkeypatch.setattr(script, "depot", depot_response)
    monkeypatch.setattr(script, "commits_on_master", lambda shas, *_: frozenset(shas) & {MASTER_SHA})

    if kept:
        assert len(script.gate_runs(trigger, 40)) == 1
    else:
        with pytest.raises(ValueError, match="No settled Backend CI verdict"):
            script.gate_runs(trigger, 40)


def test_retries_a_workflow_listing_timeout_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def depot_response(*args: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired("depot", script.CLI_TIMEOUT_SECONDS)
        return "[]"

    monkeypatch.setattr(script, "depot", depot_response)

    assert script.master_workflows(["finished"], 5, trigger="schedule") == []
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
        assert script.gate_runs("schedule", 12)[0]["conclusion"] == script.GATE_CONCLUSIONS[status]
    else:
        with pytest.raises(ValueError, match="No settled Backend CI verdict"):
            script.gate_runs("schedule", 12)


def test_gate_window_keeps_in_progress_runs_alongside_a_settled_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    def depot_response(*args: str) -> str:
        if args[:2] == ("workflow", "list"):
            return json.dumps(
                [
                    {
                        "workflow_id": status,
                        "run_id": status,
                        "sha": "abc",
                        "status": status,
                        "created_at": "2026-10-05T12:23:00Z",
                    }
                    for status in ("finished", "running")
                ]
            )
        return json.dumps({"org_id": "org", "jobs": [{"job_key": script.GATE_JOB_KEY, "status": args[2]}]})

    monkeypatch.setattr(script, "depot", depot_response)

    assert [run["status"] for run in script.gate_runs("schedule", 12)] == ["completed", "in_progress"]


@pytest.mark.parametrize("sha,found", [(MASTER_SHA, ["run-master"]), (BRANCH_SHA, [])], ids=["master", "branch"])
def test_find_trusts_only_push_runs_on_master(monkeypatch: pytest.MonkeyPatch, sha: str, found: list[str]) -> None:
    def depot_response(*args: str, **kwargs: object) -> str:
        if args[:2] == ("workflow", "list"):
            return json.dumps(
                [
                    {
                        "workflow_id": "wf",
                        "run_id": "run-master",
                        "sha": sha,
                        "status": "finished",
                        "created_at": "2099-01-01T00:00:00Z",
                    }
                ]
            )
        if args[:2] == ("artifacts", "list"):
            return json.dumps({"artifacts": [{"artifact_id": "a", "name": "migrated-schema", "created_at": "x"}]})
        raise AssertionError(args)

    monkeypatch.setattr(script, "depot", depot_response)
    monkeypatch.setattr(script, "commits_on_master", lambda shas, *_: frozenset(shas) & {MASTER_SHA})

    workflows = script.find("migrated-schema", 1, 1, 2, trigger="push", statuses=["finished"])

    assert [workflow["run_id"] for workflow in workflows] == found


def test_commits_on_master_trusts_only_comparisons_of_the_commit_asked_about(monkeypatch: pytest.MonkeyPatch) -> None:
    unknown_sha = "c" * 40
    comparisons: dict[str, dict[str, Any]] = {
        MASTER_SHA: {"status": "BEHIND", "headTarget": {"oid": MASTER_SHA}},
        BRANCH_SHA: {"status": "DIVERGED", "headTarget": {"oid": BRANCH_SHA}},
        unknown_sha: {"status": "IDENTICAL", "headTarget": {"oid": "d" * 40}},
    }

    def github_response(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        query = next(arg for arg in args if arg.startswith("query="))
        compared = {alias: comparisons[sha] for alias, sha in re.findall(r'(c\d+): compare\(headRef: "(\w+)"\)', query)}
        return subprocess.CompletedProcess(args, 0, json.dumps({"data": {"repository": {"ref": compared}}}))

    monkeypatch.setattr(subprocess, "run", github_response)

    assert script.commits_on_master([MASTER_SHA, BRANCH_SHA, unknown_sha, "not-a-sha"]) == {MASTER_SHA}


def test_download_keeps_the_newest_artifact_per_name() -> None:
    artifacts = [
        {"name": "timing_data-Core-1", "artifact_id": "retry", "created_at": "2026-10-05T12:40:00Z"},
        {"name": "timing_data-Core-1", "artifact_id": "first", "created_at": "2026-10-05T12:30:00Z"},
        {"name": "timing_data-Core-2", "artifact_id": "only", "created_at": "2026-10-05T12:31:00Z"},
    ]

    assert sorted(a["artifact_id"] for a in script.newest_per_name(artifacts)) == ["only", "retry"]


@pytest.mark.parametrize("persistent_failure", [False, True])
def test_download_recovers_from_partial_transfers_or_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, persistent_failure: bool
) -> None:
    failed = False

    def depot_response(*args: str, timeout: int = script.CLI_TIMEOUT_SECONDS) -> str:
        nonlocal failed
        if args[:2] == ("artifacts", "list"):
            return json.dumps(
                {"artifacts": [{"artifact_id": "artifact", "name": "timing_data-Core-1", "created_at": "2026-01-01"}]}
            )
        archive = Path(args[args.index("--output-file") + 1])
        if archive.exists():
            raise FileExistsError(archive)
        if persistent_failure or not failed:
            failed = True
            archive.write_bytes(b"partial archive")
            raise subprocess.CalledProcessError(1, args)
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(".test_durations", "{}")
        return ""

    monkeypatch.setattr(script, "depot", depot_response)
    monkeypatch.setattr("time.sleep", lambda _: None)

    if persistent_failure:
        with pytest.raises(subprocess.CalledProcessError):
            script.download("run", ["timing_data-*"], tmp_path)
        assert not (tmp_path / "timing_data-Core-1").exists()
    else:
        assert script.download("run", ["timing_data-*"], tmp_path) == 1
        assert (tmp_path / "timing_data-Core-1" / ".test_durations").read_text() == "{}"
