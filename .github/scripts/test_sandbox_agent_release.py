import os
import json
import subprocess
from pathlib import Path

import pytest

import yaml

ROOT = Path(__file__).resolve().parents[2]
UPDATE = ".github/workflows/update-sandbox-agent-version.yml"
BUILD = ".github/workflows/cd-sandbox-base-image.yml"
WAIT = ".github/actions/wait-for-check/action.yml"
HEAD = "a" * 40
DIGEST = "sha256:" + "b" * 64

GH = """
gh() {
    case "$*" in
        *"/check-runs "*) jq "${@: -1}" <<< "$CHECKS" ;;
        *"/jobs?"*) printf '%s' "$JOBS" ;;
        "api "*"/actions/jobs/"*) printf '%s' "$JOB" ;;
        "run download "*)
            printf '%s' "$*" > "$RUNNER_TEMP/download"
            if [ "${DOWNLOAD_STATUS:-0}" != 0 ]; then return 1; fi
            mkdir -p "$RUNNER_TEMP/sandbox-base-image"
            cp "$RUNNER_TEMP/sandbox-base-image.json" "$RUNNER_TEMP/sandbox-base-image/"
            ;;
        *) return 1 ;;
    esac
}
sleep() { SECONDS=$((SECONDS + $1)); }
"""


def script(source: str, step_id: str, job: str = "update-sandbox-agent-version") -> str:
    workflow = yaml.safe_load((ROOT / source).read_text())
    steps = workflow["jobs"][job]["steps"] if "jobs" in workflow else workflow["runs"]["steps"]
    return str(next(step["run"] for step in steps if step.get("id") == step_id))


def run(tmp_path: Path, body: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", GH + body],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_REPOSITORY": "PostHog/posthog",
            **env,
        },
        capture_output=True,
        text=True,
        timeout=5,
    )


@pytest.mark.parametrize(
    "status,conclusion", [("completed", "success"), ("completed", "failure"), ("in_progress", None)]
)
def test_wait_returns_the_latest_check_and_its_url(tmp_path: Path, status: str, conclusion: str | None) -> None:
    check = {"name": "Sandbox Base Image Smoke", "app": {"slug": "github-actions"}}
    checks = [
        {**check, "id": 1, "status": "completed", "conclusion": "success", "details_url": "old"},
        {**check, "id": 2, "status": status, "conclusion": conclusion, "details_url": "https://example.com/jobs/2"},
    ]
    result = run(
        tmp_path,
        script(WAIT, "poll"),
        CHECKS=json.dumps({"check_runs": checks}),
        CHECK_NAME="Sandbox Base Image Smoke",
        REF=HEAD,
        TIMEOUT_SECONDS="1",
        INTERVAL_SECONDS="1",
    )
    assert result.returncode == 0, result.stderr
    output = (tmp_path / "output").read_text()
    assert f"conclusion={conclusion or 'timed_out'}\n" in output
    assert f"details-url={'https://example.com/jobs/2' if conclusion else ''}\n" in output


@pytest.mark.parametrize(
    "artifact_head,digest,download_status",
    [(HEAD, DIGEST, "0"), ("c" * 40, DIGEST, "0"), (HEAD, "invalid", "0"), (HEAD, DIGEST, "1")],
)
def test_gateway_uses_the_built_digest_on_partial_reruns(
    tmp_path: Path, artifact_head: str, digest: str, download_status: str
) -> None:
    recorded = run(
        tmp_path, script(BUILD, "image-metadata", "sandbox_base_build"), HEAD_SHA=artifact_head, DIGEST=digest
    )
    assert recorded.returncode == 0, recorded.stderr
    result = run(
        tmp_path,
        script(UPDATE, "image"),
        SHA=HEAD,
        CHECK_URL="https://example.com/actions/runs/456/job/789",
        JOB=json.dumps(
            {"head_sha": HEAD, "workflow_name": "Tasks Sandbox Container Image CD", "run_id": 456, "run_attempt": 2}
        ),
        JOBS=json.dumps(
            [
                {
                    "jobs": [
                        {"name": "Build and push Tasks Sandbox container image", "run_attempt": attempt}
                        for attempt in (1, 3)
                    ]
                }
            ]
        ),
        DOWNLOAD_STATUS=download_status,
    )
    assert "--name sandbox-base-image-1 " in (tmp_path / "download").read_text()
    if artifact_head == HEAD and digest == DIGEST and download_status == "0":
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "output").read_text() == f"image=ghcr.io/posthog/posthog-sandbox-base@{DIGEST}\n"
    else:
        assert result.returncode != 0
        assert not (tmp_path / "output").exists()
