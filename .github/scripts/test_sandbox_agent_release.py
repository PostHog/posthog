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
        "api "*"/actions/runs/"*) printf '%s' "$WORKFLOW_RUN" ;;
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
        cwd=tmp_path,
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


@pytest.fixture
def image_env() -> dict[str, str]:
    branch = "chore/bump-sandbox-agent-version-2.0.1"
    return {
        "SHA": HEAD,
        "BRANCH": branch,
        "PR": "123",
        "CHECK_URL": "https://example.com/actions/runs/456/job/789",
        "JOB": json.dumps(
            {"head_sha": HEAD, "workflow_name": "Tasks Sandbox Container Image CD", "run_id": 456, "run_attempt": 2}
        ),
        "WORKFLOW_RUN": json.dumps(
            {
                "head_sha": HEAD,
                "event": "pull_request",
                "path": BUILD,
                "head_branch": branch,
                "head_repository": {"full_name": "PostHog/posthog"},
                "pull_requests": [{"number": 123, "base": {"ref": "master"}}],
            }
        ),
        "JOBS": json.dumps(
            [
                {
                    "jobs": [
                        {
                            "name": "Build and push Tasks Sandbox container image",
                            "run_attempt": attempt,
                            "started_at": f"2026-01-01T00:0{minute}:00Z",
                            "completed_at": f"2026-01-01T00:0{minute}:30Z",
                        }
                        for attempt, minute in ((1, 1), (2, 1), (3, 3))
                    ]
                }
            ]
        ),
    }


@pytest.mark.parametrize(
    "build_attempt,artifact_head,digest,download_status",
    [
        (1, HEAD, DIGEST, "0"),
        (2, HEAD, DIGEST, "0"),
        (1, "c" * 40, DIGEST, "0"),
        (1, HEAD, "invalid", "0"),
        (1, HEAD, DIGEST, "1"),
    ],
)
def test_gateway_uses_the_built_digest_on_partial_reruns(
    tmp_path: Path, image_env: dict[str, str], build_attempt: int, artifact_head: str, digest: str, download_status: str
) -> None:
    if build_attempt == 2:
        jobs = json.loads(image_env["JOBS"])
        jobs[0]["jobs"][1].update(started_at="2026-01-01T00:02:00Z", completed_at="2026-01-01T00:02:30Z")
        image_env["JOBS"] = json.dumps(jobs)
    recorded = run(
        tmp_path, script(BUILD, "image-metadata", "sandbox_base_build"), HEAD_SHA=artifact_head, DIGEST=digest
    )
    assert recorded.returncode == 0, recorded.stderr
    result = run(tmp_path, script(UPDATE, "image"), **image_env, DOWNLOAD_STATUS=download_status)
    assert f"--name sandbox-base-image-{build_attempt} " in (tmp_path / "download").read_text()
    if artifact_head == HEAD and digest == DIGEST and download_status == "0":
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "output").read_text() == f"image=ghcr.io/posthog/posthog-sandbox-base@{DIGEST}\n"
    else:
        assert result.returncode != 0
        assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "run_fields",
    [
        {"head_sha": "c" * 40},
        {"event": "push"},
        {"path": ".github/workflows/another-image.yml"},
        {"head_branch": "another-branch-at-the-same-commit"},
        {"head_repository": {"full_name": "someone/posthog"}},
        {"pull_requests": [{"number": 456, "base": {"ref": "master"}}]},
        {"pull_requests": [{"number": 123, "base": {"ref": "another-base"}}]},
        {
            "pull_requests": [
                {"number": 123, "base": {"ref": "master"}},
                {"number": 456, "base": {"ref": "another-base"}},
            ]
        },
    ],
)
def test_gateway_rejects_image_runs_outside_the_bump_pr(
    tmp_path: Path, image_env: dict[str, str], run_fields: dict[str, object]
) -> None:
    workflow_run = json.loads(image_env["WORKFLOW_RUN"])
    workflow_run.update(run_fields)
    image_env["WORKFLOW_RUN"] = json.dumps(workflow_run)
    result = run(tmp_path, script(UPDATE, "image"), **image_env)
    assert result.returncode != 0
    assert not (tmp_path / "download").exists()
    assert not (tmp_path / "output").exists()


def test_packaging_smoke_uses_each_platform_digest(tmp_path: Path) -> None:
    image = "ghcr.io/posthog/posthog-sandbox-base"
    digests = {"amd64": "sha256:" + "c" * 64, "arm64": "sha256:" + "d" * 64}
    dockerfile = tmp_path / "products/tasks/backend/sandbox/images/Dockerfile.sandbox-base"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("ARG AGENT_VERSION=2.0.1\n")
    manifest = {
        "manifests": [
            {"platform": {"os": "linux", "architecture": arch}, "digest": digest} for arch, digest in digests.items()
        ]
    }
    docker = """
docker() {
    case "$*" in
        "manifest inspect "*) printf '%s' "$MANIFEST" ;;
        "run "*)
            printf '%s %s\\n' "$4" "$5" >> "$RUNNER_TEMP/containers"
            printf '%s' "$PINNED"
            ;;
        *) return 1 ;;
    esac
}
"""
    result = run(
        tmp_path,
        docker + script(BUILD, "smoke", "sandbox_base_build"),
        IMAGE=f"{image}@{DIGEST}",
        MANIFEST=json.dumps(manifest),
        PINNED="2.0.1",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "containers").read_text().splitlines() == [
        f"linux/{arch} {image}@{digest}" for arch, digest in digests.items() for _ in range(2)
    ]
