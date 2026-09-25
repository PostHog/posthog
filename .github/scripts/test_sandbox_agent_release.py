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
DOCKERFILE = "products/tasks/backend/sandbox/images/Dockerfile.sandbox-base"

GH = """
gh() {
    case "$*" in
        "pr list "*) printf '123 chore/bump-sandbox-agent-version-2.0.1\\n' ;;
        "api graphql "*) return 0 ;;
        *"/check-runs "*) jq "${@: -1}" <<< "$CHECKS" ;;
        *"/jobs?"*) printf '%s' "$JOBS" ;;
        "api "*"/actions/jobs/"*) printf '%s' "$JOB" ;;
        "run download "*)
            printf '%s' "$*" > "$RUNNER_TEMP/download"
            if [ "${DOWNLOAD_STATUS:-0}" != 0 ]; then return 1; fi
            mkdir -p "$RUNNER_TEMP/sandbox-base-image"
            cp "$RUNNER_TEMP/sandbox-base-image.json" "$RUNNER_TEMP/sandbox-base-image/"
            ;;
        "api "*"/files "*) printf '%s' "$FILES" ;;
        "api "*"/pulls/"*) printf '%s' "$PR_DATA" ;;
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
            "DOCKERFILE": DOCKERFILE,
            "BRANCH": "chore/bump-sandbox-agent-version-2.0.1",
            "LATEST": "2.0.1",
            "PINNED": "2.0.0",
            "APP_SLUG": "scheduled-actions-posthog",
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
        if download_status != "0":
            assert "Update the bump branch from master" in result.stdout


@pytest.mark.parametrize("event,action", [("workflow_dispatch", "resume"), ("schedule", "current")])
def test_existing_pr_resumes_only_on_dispatch(tmp_path: Path, event: str, action: str) -> None:
    result = run(tmp_path, script(UPDATE, "state"), EVENT_NAME=event, REPO="PostHog/posthog")
    assert result.returncode == 0, result.stderr
    assert f"action={action}\n" in (tmp_path / "output").read_text()
    assert "current_pr=123\n" in (tmp_path / "output").read_text()


@pytest.mark.parametrize(
    "author,extra_file",
    [("scheduled-actions-posthog[bot]", False), ("someone-else", False), ("scheduled-actions-posthog[bot]", True)],
)
def test_resume_only_accepts_the_automated_pin_change(tmp_path: Path, author: str, extra_file: bool) -> None:
    files = [
        {
            "filename": DOCKERFILE,
            "status": "modified",
            "additions": 1,
            "deletions": 1,
            "patch": "@@ -1 +1 @@\n-ARG AGENT_VERSION=2.0.0\n+ARG AGENT_VERSION=2.0.1",
        }
    ]
    if extra_file:
        files.append({"filename": "another-file"})
    result = run(
        tmp_path,
        script(UPDATE, "candidate"),
        PR="123",
        PR_DATA=json.dumps(
            {
                "state": "open",
                "base": {"ref": "master"},
                "head": {
                    "sha": HEAD,
                    "ref": "chore/bump-sandbox-agent-version-2.0.1",
                    "repo": {"full_name": "PostHog/posthog"},
                },
                "user": {"login": author},
                "html_url": "https://example.com/pull/123",
            }
        ),
        FILES=json.dumps(files),
    )
    if author == "scheduled-actions-posthog[bot]" and not extra_file:
        assert result.returncode == 0, result.stderr
        assert f"sha={HEAD}\n" in (tmp_path / "output").read_text()
    else:
        assert result.returncode != 0
        assert not (tmp_path / "output").exists()
