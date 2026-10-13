#!/usr/bin/env python3
"""Read the hourly Backend CI runs on Depot CI: their verdicts and their artifacts.

The hourly master run of Backend CI lives on Depot CI, which keeps its runs and artifacts
apart from GitHub Actions. This is the Depot counterpart of listing workflow runs with
`gh api` and fetching artifacts with `gh run download`.

    depot_scheduled_runs.py find --prefix timing_data- --min-artifacts 38 --limit 5
    depot_scheduled_runs.py download <run-id> --pattern 'timing_data-Core-*' --dir timing
    depot_scheduled_runs.py gate-runs

`find` prints one `<run-id> <sha>` line per successful run, newest first. `download` unpacks
each matching artifact into `<dir>/<artifact name>/`, the layout `gh run download` produces.
`gate-runs` prints the newest runs as JSON, each with the conclusion of its gate job, in the
shape .github/scripts/ci-alerts-devex.js reads GitHub workflow runs in.
Needs the `depot` CLI and DEPOT_TOKEN.
"""

from __future__ import annotations

import sys
import json
import time
import fnmatch
import zipfile
import argparse
import tempfile
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict, cast

REPO = "PostHog/posthog"
# Both match .github/scripts/ci_backend_relay.py, which reads the same workflow for pull requests.
WORKFLOW_NAME = "Backend CI on Depot"
GATE_JOB_KEY = "ci-backend.yml:django_tests"
GATE_CONCLUSIONS = {"finished": "success", "failed": "failure", "cancelled": "cancelled"}
ENDED = frozenset(GATE_CONCLUSIONS)
# Short enough that the alerter's read of GATE_RUNS_LISTED runs ends inside its step timeout.
CLI_TIMEOUT_SECONDS = 10
DOWNLOAD_TIMEOUT_SECONDS = 120
PARALLEL_CLI_CALLS = 8
# The Depot CLI returns at most 200 workflows, which is 8 days of hourly runs.
MAX_LISTED = 200
# The alerter resolves an incident when no listed run is a settled failure, so the window has
# to outlast a stretch of hung or cancelled runs.
GATE_RUNS_LISTED = 12


class ListedWorkflow(TypedDict):
    workflow_id: str
    run_id: str
    sha: str
    status: str
    created_at: str


class Artifact(TypedDict):
    artifact_id: str
    name: str
    created_at: str


class Job(TypedDict, total=False):
    job_key: str
    status: str
    finished_at: str


class ShownWorkflow(TypedDict):
    org_id: str
    jobs: list[Job]


class GateRun(TypedDict):
    id: str
    name: str
    status: str
    conclusion: str | None
    head_sha: str
    html_url: str
    created_at: str
    updated_at: str


def depot(*args: str, timeout: int = CLI_TIMEOUT_SECONDS) -> str:
    # stderr passes through, so a failed call explains itself in the job log.
    result = subprocess.run(["depot", "ci", *args], check=True, stdout=subprocess.PIPE, text=True, timeout=timeout)
    return result.stdout


def scheduled_workflows(statuses: list[str], limit: int, *, repo: str = REPO) -> list[ListedWorkflow]:
    """The hourly Backend CI workflows in the given states, newest first."""
    args = ["workflow", "list", "--repo", repo, "--name", WORKFLOW_NAME, "--trigger", "schedule", "-n", str(limit)]
    for status in statuses:
        args += ["--status", status]
    # The CLI prints `null` when nothing matches.
    try:
        output = depot(*args, "--output", "json")
    except subprocess.TimeoutExpired:
        output = depot(*args, "--output", "json")
    workflows = cast(list[ListedWorkflow], json.loads(output or "null") or [])
    return sorted(workflows, key=lambda w: w["created_at"], reverse=True)


def artifacts(run_id: str) -> list[Artifact]:
    listed = json.loads(depot("artifacts", "list", run_id, "--output", "json") or "null") or {}
    return cast(list[Artifact], listed.get("artifacts") or [])


def newest_per_name(run_artifacts: list[Artifact]) -> list[Artifact]:
    """A retried job uploads its artifact again under the same name. Keep the newest."""
    newest: dict[str, Artifact] = {}
    for artifact in sorted(run_artifacts, key=lambda a: a["created_at"]):
        newest[artifact["name"]] = artifact
    return list(newest.values())


def find(prefix: str, min_artifacts: int, limit: int, max_age_days: int) -> list[ListedWorkflow]:
    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: list[ListedWorkflow] = []
    for workflow in scheduled_workflows(["finished"], MAX_LISTED):
        if workflow["created_at"] < cutoff:
            break
        try:
            names = {a["name"] for a in artifacts(workflow["run_id"]) if a["name"].startswith(prefix)}
        except (subprocess.SubprocessError, json.JSONDecodeError) as error:
            sys.stderr.write(f"Run {workflow['run_id']}: could not list artifacts, skipping it: {error!r}\n")
            continue
        sys.stderr.write(f"Run {workflow['run_id']} has {len(names)} {prefix}* artifacts\n")
        if len(names) >= min_artifacts:
            found.append(workflow)
            if len(found) >= limit:
                break
    return found


def download(run_id: str, patterns: list[str], directory: Path) -> int:
    matching = [
        a for a in newest_per_name(artifacts(run_id)) if any(fnmatch.fnmatchcase(a["name"], p) for p in patterns)
    ]
    with tempfile.TemporaryDirectory() as scratch:

        def fetch(artifact: Artifact) -> None:
            archive = Path(scratch) / f"{artifact['artifact_id']}.zip"
            for attempt in range(3):
                try:
                    depot(
                        "artifacts",
                        "download",
                        artifact["artifact_id"],
                        "--output-file",
                        str(archive),
                        timeout=DOWNLOAD_TIMEOUT_SECONDS,
                    )
                    break
                except subprocess.SubprocessError:
                    # The CLI refuses to overwrite a file left by a partial download.
                    archive.unlink(missing_ok=True)
                    if attempt == 2:
                        raise
                    sys.stderr.write(f"Artifact {artifact['name']}: download failed, retrying\n")
                    time.sleep(2**attempt)
            target = directory / artifact["name"]
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(target)

        # One CLI call per artifact, and an hourly refresh downloads several hundred.
        with ThreadPoolExecutor(max_workers=PARALLEL_CLI_CALLS) as pool:
            list(pool.map(fetch, matching))
    return len(matching)


def gate_run(listed: ListedWorkflow) -> GateRun:
    """One workflow as a GitHub-shaped run. A workflow whose gate job has not ended is not completed."""
    shown = cast(ShownWorkflow, json.loads(depot("workflow", "show", listed["workflow_id"], "--output", "json")))
    gate = next((job for job in shown.get("jobs") or [] if job.get("job_key") == GATE_JOB_KEY), None)
    conclusion: str | None = None
    if gate and gate.get("status") in GATE_CONCLUSIONS:
        conclusion = GATE_CONCLUSIONS[gate["status"]]
    elif listed["status"] in ENDED:
        # An hourly run that ended without a gate verdict ran no tests. The alerter drops
        # skipped runs, so reporting one as skipped would hide a lane that tests nothing.
        conclusion = "cancelled" if listed["status"] == "cancelled" else "failure"
    return {
        "id": listed["run_id"],
        "name": "Backend CI",
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "head_sha": listed["sha"],
        "html_url": f"https://depot.dev/orgs/{shown['org_id']}/workflows/{listed['workflow_id']}",
        "created_at": listed["created_at"],
        "updated_at": (gate or {}).get("finished_at") or listed["created_at"],
    }


def gate_runs() -> list[GateRun]:
    listed = scheduled_workflows(["queued", "running", *sorted(ENDED)], GATE_RUNS_LISTED)
    with ThreadPoolExecutor(max_workers=PARALLEL_CLI_CALLS) as pool:
        runs = list(pool.map(gate_run, listed))
    # An empty or inconclusive window must not resolve an existing CI incident.
    if not any(
        run["status"] == "completed" and run["conclusion"] not in (None, "cancelled", "skipped") for run in runs
    ):
        raise ValueError("No settled Backend CI verdict in the scheduled run window")
    return runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    find_parser = commands.add_parser("find")
    find_parser.add_argument("--prefix", required=True)
    find_parser.add_argument("--min-artifacts", type=int, default=1)
    find_parser.add_argument("--limit", type=int, default=1)
    find_parser.add_argument("--max-age-days", type=int, default=14)
    download_parser = commands.add_parser("download")
    download_parser.add_argument("run_id")
    download_parser.add_argument("--pattern", action="append", required=True)
    download_parser.add_argument("--dir", type=Path, required=True)
    commands.add_parser("gate-runs")
    args = parser.parse_args()

    if args.command == "find":
        for workflow in find(args.prefix, args.min_artifacts, args.limit, args.max_age_days):
            sys.stdout.write(f"{workflow['run_id']} {workflow['sha']}\n")
        return 0
    if args.command == "gate-runs":
        json.dump(gate_runs(), sys.stdout)
        return 0
    count = download(args.run_id, args.pattern, args.dir)
    sys.stderr.write(f"Downloaded {count} artifacts matching {args.pattern} from run {args.run_id}\n")
    # `gh run download` fails when nothing matches, and the callers rely on that.
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
