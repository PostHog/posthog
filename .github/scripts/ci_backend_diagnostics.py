#!/usr/bin/env python3
"""Read-only Depot evidence for a check posted by a default-branch workflow_run job.

Request artifacts are untrusted hints, never code or authority. GitHub checks supply the
verdict; this module can only explain it. No third-party Python packages are installed.
"""

import io
import os
import re
import sys
import json
import time
import zipfile
import selectors
import subprocess
import urllib.parse
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any, BinaryIO

from ci_backend_relay import (
    API_ROOT,
    DEPOT_ORG,
    DEPOT_WORKFLOW,
    GATE_CHECK,
    CheckRun,
    CheckRunReader,
    Event,
    Phase,
    poll,
)

REPO = "PostHog/posthog"
MAX_BYTES = 2_000_000
MAX_REPORT = 24_000
MAX_FAILURES = 5
ID = re.compile(r"[a-z0-9]{1,32}\Z")
SHA = re.compile(r"[a-f0-9]{40}\Z")
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
SECRET = re.compile(
    r"(?i)(?:(?:bearer|basic)\s+\S+|"
    r"""\b[\w-]*(?:token|password|secret|authorization|cookie|api[_-]?key)[\w-]*["']?\s*[:=]\s*(?:"[^"]*(?:"|$)|'[^']*(?:'|$)|[^\s,;]+)|"""
    r"(?:gh[pousr]_|github_pat_|sk[-_]|ph[ctx]_|depot_)[A-Za-z0-9_\-]{8,}|"
    r"AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"[a-f0-9]{64,}|-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)|"
    r"https?://[^\s/@]+:[^\s/@]+@[^\s]+)"
)
FAILURE = re.compile(r"FAILED|ERROR|Error|Exception|Assertion|fatal|panic|timed out|exit(?:ed)? (?:with )?code")


class Unavailable(ValueError):
    pass


def safe_text(value: str, limit: int = 800, *, markdown: bool = True) -> str:
    text = ANSI.sub("", value[:8192])
    text = "".join(c for c in text if c.isprintable() or c in "\n\t")
    text = SECRET.sub("[REDACTED]", text)
    for name in ("DEPOT_TOKEN", "GH_TOKEN"):
        if token := os.environ.get(name):
            text = text.replace(token, "[REDACTED]")
    # Encode markup AND workflow command delimiters; every excerpt stays one inert line.
    text = text.replace("\n", " ").replace("\t", " ")
    return re.sub(r"([&\\`*_{}\[\]<>()#!|:])", lambda m: f"&#{ord(m[1])};", text[:limit]) if markdown else text[:limit]


def publish(lines: list[str]) -> None:
    rendered = (
        "\n".join(safe_text(line, 1600, markdown=False).replace("::", ": :") for line in lines)[:MAX_REPORT] + "\n"
    )
    sys.stdout.write(rendered)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as stream:
            stream.write("\n\n".join(safe_text(line, 1600) for line in lines)[:MAX_REPORT] + "\n")


class ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: urllib.request.Request, fp: BinaryIO, code: int, msg: str, headers: Message, newurl: str
    ) -> urllib.request.Request | None:
        target = urllib.parse.urlparse(newurl)
        if target.scheme != "https":
            raise Unavailable("insecure redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        # Signed artifact URLs must not receive the GitHub credential.
        if redirected and target.netloc != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: urllib.request.Request, fp: BinaryIO, code: int, msg: str, headers: Message, newurl: str
    ) -> None:
        return None


class GitHub:
    def __init__(self, token: str) -> None:
        self.token = token

    def read(self, path: str, *, binary: bool = False) -> Any:
        request = urllib.request.Request(
            f"{API_ROOT}/repos/{REPO}/{path}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"},
        )

        with urllib.request.build_opener(ArtifactRedirect()).open(request, timeout=15) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise Unavailable("response size limit")
        return raw if binary else json.loads(raw)

    def artifact(self, run: int, name: str) -> dict[str, Any] | None:
        body = self.read(f"actions/runs/{run}/artifacts?per_page=100&name={urllib.parse.quote(name)}")
        matches = [a for a in body["artifacts"] if a["name"] == name and not a["expired"]]
        if len(matches) != 1:
            if matches:
                raise Unavailable("ambiguous artifact")
            return None
        item = matches[0]
        if item["size_in_bytes"] > MAX_REPORT:
            raise Unavailable("artifact size limit")
        raw = self.read(f"actions/artifacts/{int(item['id'])}/zip", binary=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) != 1 or entries[0].file_size > MAX_REPORT or entries[0].filename != "diagnostics.json":
                raise Unavailable("invalid artifact archive")
            value = json.loads(archive.read(entries[0]))
        if not isinstance(value, dict):
            raise Unavailable("invalid artifact JSON")
        return value

    def handoff(self, run: int, attempt: int) -> str | None:
        body = self.read(f"actions/runs/{run}/attempts/{attempt}/jobs?per_page=100")
        if body["total_count"] > 100:
            raise Unavailable("job listing incomplete")
        jobs = [job for job in body["jobs"] if job["name"] == "Hand off backend tests to Depot CI"]
        return jobs[0]["conclusion"] if len(jobs) == 1 else None

    def create_check(self, request: dict[str, Any], summary: str) -> None:
        payload = {
            "name": f"Backend Depot diagnostics ({request['github_run']}.{request['github_attempt']})",
            "head_sha": request["sha"],
            "status": "completed",
            "conclusion": "neutral",
            "details_url": f"https://github.com/{REPO}/actions/runs/{int(os.environ['GITHUB_RUN_ID'])}",
            "output": {"title": "Depot backend failure details", "summary": summary},
        }
        api_request = urllib.request.Request(
            f"{API_ROOT}/repos/{REPO}/check-runs",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.build_opener(NoRedirect()).open(api_request, timeout=15):
            pass


class Depot:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + 100
        self.requests = 0

    def read(self, *args: str, json_lines: bool = False) -> Any:
        self.requests += 1
        remaining = min(25, self.deadline - time.monotonic())
        if self.requests > 10 or remaining <= 0:
            raise Unavailable("collection budget exhausted")
        # No shell, suggested commands, PR dependencies, or PR working directory.
        with subprocess.Popen(
            ["depot", "ci", *args, "--org", DEPOT_ORG, "--output", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd="/tmp",
            env={
                "PATH": os.environ["PATH"],
                "HOME": "/tmp/depot-diagnostics-home",
                "DEPOT_TOKEN": os.environ.get("DEPOT_TOKEN", ""),
            },
        ) as process:
            assert process.stdout is not None
            end = time.monotonic() + remaining
            raw = bytearray()
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        if time.monotonic() >= end or not selector.select(max(0, end - time.monotonic())):
                            raise Unavailable("Depot request deadline")
                        block = os.read(process.stdout.fileno(), 65536)
                        if not block:
                            break
                        raw.extend(block)
                        if len(raw) > MAX_BYTES:
                            raise Unavailable("Depot response size limit")
                if process.wait(timeout=max(0.1, end - time.monotonic())):
                    raise Unavailable("Depot request failed")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        if json_lines:
            return [json.loads(line) for line in raw.splitlines() if line.strip()]
        return json.loads(raw)


def validate_request(request: dict[str, Any], run: dict[str, Any], handoff: str | None) -> Event:
    if (
        set(request)
        != {"repo", "sha", "pr", "event_at", "github_run", "github_attempt", "workflow", "root_check_id", "check_id"}
        or not isinstance(request["event_at"], str)
        or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", request["event_at"])
        or any(
            type(request[key]) is not int or request[key] < 0
            for key in ("pr", "github_run", "github_attempt", "root_check_id", "check_id")
        )
        or request["repo"] != REPO
        or run["path"] != ".github/workflows/ci-backend.yml"
        or run["event"] != "pull_request"
        or run["head_repository"]["full_name"] != REPO
        or request["github_run"] != run["id"]
        or request["github_attempt"] != run["run_attempt"]
        or request["sha"] != run["head_sha"]
        or not SHA.fullmatch(request["sha"])
        or not ID.fullmatch(request["workflow"] or "")
        or not any(pr["number"] == request["pr"] and pr["head"]["sha"] == request["sha"] for pr in run["pull_requests"])
    ):
        raise Unavailable("request identity mismatch")
    if handoff != "success":
        raise Unavailable("no successful GitHub handoff")
    return Event(REPO, request["sha"], request["pr"], request["event_at"])


def validate_workflow(body: dict[str, Any], event: Event, workflow: str) -> None:
    run, selected = body["run"], body["workflow"]
    if (
        body["org_id"] != DEPOT_ORG
        or run["repo"] != event.repo
        or run["head_sha"] != event.sha
        or not SHA.fullmatch(run["sha"])
        or run["ref"] != f"refs/pull/{event.pr_number}/merge"
        or run["trigger"] != "pull_request"
        or selected["workflow_id"] != workflow
        or selected["workflow_path"] != "ci-backend.yml"
        or selected["name"] != DEPOT_WORKFLOW
        or not ID.fullmatch(run["run_id"])
    ):
        raise Unavailable("Depot workflow identity mismatch")


def deterministic_boundary(logs: list[dict[str, Any]], job_key: str) -> bool:
    # Step metadata is assigned by the orchestrator. A log body claiming to be this
    # step, or merely containing an assertion, is not the classifier signal.
    flagged = any(
        line.get("type") == "line"
        and line.get("step_id") == "deterministic-failure"
        and line.get("step_name") == "Flag deterministic failure"
        and line.get("body") == '##[group]Run echo "deterministic_failure=true" >> "$GITHUB_OUTPUT"'
        for line in logs
    )
    if job_key == "ci-backend.yml:repo-checks":
        return flagged
    # The OpenAPI step also runs git ls-remote and generation subprocesses. Its
    # failure flag alone cannot distinguish those failures from generated-file drift.
    return (
        flagged
        and job_key == "ci-backend.yml:check-openapi-types"
        and any(
            line.get("step_id") == "openapi-check" and line.get("body") == "::error::OpenAPI types are out of date!"
            for line in logs
        )
    )


def collect(depot: Depot, event: Event, workflow: str) -> list[str]:
    body = depot.read("workflow", "show", workflow)
    validate_workflow(body, event, workflow)
    run_id = body["run"]["run_id"]
    lines = [f"Depot run {run_id}; workflow {workflow}; PR head {event.sha}; merge SHA {body['run']['sha']}."]
    failed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for job in body["jobs"]:
        attempt = max(job["attempts"], key=lambda a: a["attempt"], default=None)
        if job["status"] == "failed" and attempt and attempt["status"] == "failed":
            failed.append((job, attempt))
    roots = [(job, attempt) for job, attempt in failed if job["job_key"] != "ci-backend.yml:django_tests"]
    if roots and len(roots) != len(failed):
        lines.append("Downstream Django Tests Pass gate failed after prerequisite failures.")
        failed = roots
    if not failed:
        return [*lines, "Diagnostics unavailable: no current failed attempts. Retryability: unknown."]
    diagnosis = depot.read("diagnose", "--workflow", workflow)
    context = diagnosis["context"]
    if (
        diagnosis["org_id"] != DEPOT_ORG
        or context["run_id"] != run_id
        or context["repo"] != event.repo
        or context["head_sha"] != event.sha
        or context["sha"] != body["run"]["sha"]
        or context["workflow_id"] != workflow
        or context["workflow_path"] != "ci-backend.yml"
        or context["ref"] != body["run"]["ref"]
        or context.get("truncated_context_fields")
        or diagnosis["target"]["target_id"] != workflow
        or diagnosis["target"]["target_type"] != "workflow"
    ):
        raise Unavailable("diagnosis identity mismatch")
    deterministic = False
    recovered_attempts: list[str] = []
    for job, attempt in failed[:MAX_FAILURES]:
        if not ID.fullmatch(attempt["attempt_id"]):
            raise Unavailable("invalid attempt")
        lines.append(f"Failed job: {job['job_key']}; attempt {attempt['attempt']} ({attempt['attempt_id']}).")
        prior_successes = [
            a for a in job["attempts"] if a["attempt"] < attempt["attempt"] and a["status"] == "finished"
        ]
        if prior_successes:
            recovered_attempts.append(
                f"{job['job_key']} previously passed attempt {max(prior_successes, key=lambda a: a['attempt'])['attempt_id']}"
            )
        representative = next(
            (
                r
                for r in diagnosis["representative_attempts"]
                if r["job_id"] == job["job_id"] and r["attempt_id"] == attempt["attempt_id"]
            ),
            None,
        )
        if representative is None:
            lines.append("Step diagnostics unavailable for this attempt.")
        else:
            if (
                representative["run_id"] != run_id
                or representative["workflow_id"] != workflow
                or representative["workflow_path"] != "ci-backend.yml"
                or representative["job_key"] != job["job_key"]
                or representative["attempt"] != attempt["attempt"]
                or representative["attempt_status"] != "failed"
                or representative["job_status"] != "failed"
            ):
                raise Unavailable("diagnosis attempt mismatch")
            lines.append(f"Failed step: {representative['error_message']}")
            # diagnosis / possible_fix are AI advice, not failure or retryability evidence.
            excerpts = sorted(
                (e["content"] for e in representative["relevant_lines"] if FAILURE.search(e["content"])),
                key=lambda text: not text.startswith(("FAILED ", "ERROR ", "E ")),
            )
            for excerpt in excerpts[:4]:
                lines.append(f"Evidence: {excerpt}")
        if job["job_key"] in ("ci-backend.yml:repo-checks", "ci-backend.yml:check-openapi-types"):
            logs = depot.read("logs", attempt["attempt_id"], json_lines=True)
            deterministic |= deterministic_boundary(logs, job["job_key"])
    # Don't publish an attempt that was replaced during collection.
    current = depot.read("workflow", "show", workflow)
    validate_workflow(current, event, workflow)
    if (
        current["jobs"] != body["jobs"]
        or current["executions"] != body["executions"]
        or any(current["run"][key] != body["run"][key] for key in ("run_id", "sha"))
    ):
        raise Unavailable("Depot attempts changed during collection")
    if diagnosis.get("bounds", {}).get("truncated") or len(failed) > MAX_FAILURES:
        lines.append("Diagnostics truncated: only a bounded subset of failures is shown.")
    cancelled = sum(j["status"] == "cancelled" for j in body["jobs"])
    if deterministic:
        lines += [
            "Retryability: confirmed deterministic by the prerequisite classifier step.",
            f"Expected downstream cancellations: {cancelled} jobs. Fix the prerequisite failure and push the fix.",
        ]
    else:
        lines += [
            f"Cancelled jobs: {cancelled}; cancellation cause not established.",
            ("Retryability: possible flake with retry evidence: " + "; ".join(recovered_attempts))
            if recovered_attempts
            else "Retryability: unknown. An assertion or AI diagnosis alone does not establish a flake.",
            "Inspect the failed step and fix it when needed. Without Depot access, push a new commit to retry.",
            "A fresh commit goes through GitHub's router; routing rules choose its engine.",
        ]
    return lines


def read_request(github: GitHub, trigger: dict[str, Any], destination: Path) -> None:
    run_id, attempt = trigger["id"], trigger["run_attempt"]
    if os.environ.get("HAS_DEPOT_CREDENTIAL") != "true":
        publish(["Diagnostics unavailable: DEPOT_TOKEN is not available to the trusted GitHub collector."])
        return
    run = github.read(f"actions/runs/{run_id}")
    if run["run_attempt"] != attempt or run["status"] != "completed":
        return
    request = github.artifact(run_id, f"backend-diagnostics-request-{run_id}-{attempt}")
    if request is None:
        return
    validate_request(request, run, github.handoff(run_id, attempt))
    validate_selection(github, request)
    destination.write_text(json.dumps(request))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write("ready=true\n")


def validate_selection(github: GitHub, request: dict[str, Any]) -> Event:
    event = Event(REPO, request["sha"], request["pr"], request["event_at"])
    selected = poll(
        CheckRunReader(REPO, event.sha, github.token, pr_number=event.pr_number),
        event,
        GATE_CHECK,
        deadline_minutes=0,
        absent_minutes=0,
    )
    if (
        CheckRun(0, "", selected.details_url).depot_workflow != request["workflow"]
        or selected.check_id != request["check_id"]
        or selected.root_check_id != request["root_check_id"]
        or (selected.phase == Phase.FINISHED and selected.state == "success")
    ):
        raise Unavailable("selected workflow or attempt changed")
    return event


def check_summary(lines: list[str]) -> str:
    parts: list[str] = []
    for line in lines[:40]:
        rendered = safe_text(line, 1600)
        if len("\n\n".join([*parts, rendered]).encode()) > MAX_REPORT - 100:
            parts.append("Diagnostics truncated to the report size limit.")
            break
        parts.append(rendered)
    return "\n\n".join(parts)


def collector(github: GitHub, request: dict[str, Any]) -> None:
    if len(json.dumps(request).encode()) > 4000:
        raise Unavailable("oversized request")
    if not os.environ.get("DEPOT_TOKEN"):
        raise Unavailable("missing Depot credential")
    run = github.read(f"actions/runs/{request['github_run']}")
    if run["status"] != "completed":
        raise Unavailable("GitHub run changed during collection")
    validate_request(request, run, github.handoff(request["github_run"], request["github_attempt"]))
    event = validate_selection(github, request)
    try:
        lines = collect(Depot(), event, request["workflow"])
    except Exception:
        lines = ["Diagnostics unavailable: collection failed or evidence could not be validated."]
    run = github.read(f"actions/runs/{request['github_run']}")
    if run["status"] != "completed":
        raise Unavailable("GitHub run changed during collection")
    validate_request(request, run, github.handoff(request["github_run"], request["github_attempt"]))
    validate_selection(github, request)
    github.create_check(request, check_summary(lines))
    publish(lines)


def main() -> int:
    github = GitHub(os.environ["GH_TOKEN"])
    try:
        if sys.argv[1:] == ["read-request"]:
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
            if (
                event["repository"]["full_name"] != REPO
                or event["repository"]["default_branch"] != "master"
                or event["workflow_run"]["event"] != "pull_request"
            ):
                raise Unavailable("unexpected collector event")
            read_request(github, event["workflow_run"], Path(os.environ["REQUEST_FILE"]))
        elif sys.argv[1:] == ["collect"]:
            collector(github, json.loads(Path(os.environ["REQUEST_FILE"]).read_text()))
        else:
            return 2
    except Exception:
        publish(["Diagnostics unavailable: collection or validation failed. The original relay verdict is unchanged."])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
