#!/usr/bin/env python3
"""Read the hourly Backend CI runs on Depot CI: their verdicts and their artifacts.

The hourly master run of Backend CI lives on Depot CI, which keeps its runs and artifacts
apart from GitHub Actions. This is the Depot counterpart of listing workflow runs with
`gh api` and fetching artifacts with `gh run download`.

    depot_scheduled_runs.py find --prefix timing_data- --min-artifacts 38 --limit 5
    depot_scheduled_runs.py download <run-id> --pattern 'timing_data-Core-*' --dir timing
    depot_scheduled_runs.py gate-runs --limit 6

`find` prints one `<run-id> <sha>` line per successful run, newest first. `download` unpacks
each matching artifact into `<dir>/<artifact name>/`, the layout `gh run download` produces.
`gate-runs` prints the newest runs as JSON, each with the conclusion of its gate job, in the
shape .github/scripts/ci-alerts-devex.js reads GitHub workflow runs in.
Needs the `depot` CLI and DEPOT_TOKEN.
"""

from __future__ import annotations

import sys
import json
import fnmatch
import zipfile
import argparse
import tempfile
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = "PostHog/posthog"
WORKFLOW_NAME = "Backend CI on Depot"
# The job behind the `Django Tests Pass on Depot` check in .depot/workflows/ci-backend.yml.
GATE_JOB_KEY = "ci-backend.yml:django_tests"
CLI_TIMEOUT_SECONDS = 120
# The Depot CLI returns at most 200 workflows, which is 8 days of hourly runs.
MAX_LISTED = 200
GITHUB_CONCLUSIONS = {"finished": "success", "failed": "failure", "cancelled": "cancelled", "skipped": "skipped"}


def depot_json(*args: str) -> Any:
    result = subprocess.run(
        ["depot", "ci", *args, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT_SECONDS,
    )
    # The CLI prints `null` when nothing matches.
    return json.loads(result.stdout or "null")


def scheduled_workflows(statuses: list[str], limit: int) -> list[dict[str, Any]]:
    """The hourly Backend CI workflows in the given states, newest first."""
    args = ["workflow", "list", "--repo", REPO, "--name", WORKFLOW_NAME, "--trigger", "schedule", "-n", str(limit)]
    for status in statuses:
        args += ["--status", status]
    workflows = depot_json(*args) or []
    return sorted(workflows, key=lambda w: w["created_at"], reverse=True)


def artifacts(run_id: str) -> list[dict[str, Any]]:
    return (depot_json("artifacts", "list", run_id) or {}).get("artifacts") or []


def newest_per_name(run_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A retried job uploads its artifact again under the same name. Keep the newest."""
    newest: dict[str, dict[str, Any]] = {}
    for artifact in sorted(run_artifacts, key=lambda a: a["created_at"]):
        newest[artifact["name"]] = artifact
    return list(newest.values())


def find(prefix: str, min_artifacts: int, limit: int, max_age_days: int) -> list[tuple[str, str]]:
    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: list[tuple[str, str]] = []
    for workflow in scheduled_workflows(["finished"], MAX_LISTED):
        if workflow["created_at"] < cutoff:
            break
        names = {a["name"] for a in artifacts(workflow["run_id"]) if a["name"].startswith(prefix)}
        sys.stderr.write(f"Run {workflow['run_id']} has {len(names)} {prefix}* artifacts\n")
        if len(names) >= min_artifacts:
            found.append((workflow["run_id"], workflow["sha"]))
            if len(found) >= limit:
                break
    return found


def download(run_id: str, patterns: list[str], directory: Path) -> int:
    matching = [
        a for a in newest_per_name(artifacts(run_id)) if any(fnmatch.fnmatchcase(a["name"], p) for p in patterns)
    ]
    with tempfile.TemporaryDirectory() as scratch:
        for artifact in matching:
            archive = Path(scratch) / f"{artifact['artifact_id']}.zip"
            subprocess.run(
                ["depot", "ci", "artifacts", "download", artifact["artifact_id"], "--output-file", str(archive)],
                check=True,
                capture_output=True,
                timeout=CLI_TIMEOUT_SECONDS,
            )
            target = directory / artifact["name"]
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(target)
    return len(matching)


def gate_run(listed: dict[str, Any]) -> dict[str, Any]:
    """One workflow as a GitHub-shaped run. A workflow whose gate job has not ended is not completed."""
    shown = depot_json("workflow", "show", listed["workflow_id"])
    gate = next((job for job in shown.get("jobs") or [] if job["job_key"] == GATE_JOB_KEY), None)
    workflow_ended = listed["status"] in ("finished", "failed", "cancelled")
    if gate and gate["status"] in GITHUB_CONCLUSIONS:
        status, conclusion = "completed", GITHUB_CONCLUSIONS[gate["status"]]
    elif workflow_ended:
        # The gate never ran, so the workflow's own state is the only verdict there is.
        status, conclusion = "completed", GITHUB_CONCLUSIONS[listed["status"]]
    else:
        status, conclusion = "in_progress", None
    return {
        "id": listed["run_id"],
        "name": "Backend CI",
        "status": status,
        "conclusion": conclusion,
        "head_sha": listed["sha"],
        "html_url": f"https://depot.dev/orgs/{shown['org_id']}/workflows/{listed['workflow_id']}",
        "created_at": listed["created_at"],
        "updated_at": (gate or {}).get("finished_at") or shown["workflow"].get("finished_at") or listed["created_at"],
    }


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
    gate_parser = commands.add_parser("gate-runs")
    gate_parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()

    if args.command == "find":
        for run_id, sha in find(args.prefix, args.min_artifacts, args.limit, args.max_age_days):
            sys.stdout.write(f"{run_id} {sha}\n")
        return 0
    if args.command == "gate-runs":
        listed = scheduled_workflows(["queued", "running", "finished", "failed", "cancelled"], args.limit)
        json.dump([gate_run(workflow) for workflow in listed], sys.stdout)
        return 0
    count = download(args.run_id, args.pattern, args.dir)
    sys.stderr.write(f"Downloaded {count} artifacts matching {args.pattern} from run {args.run_id}\n")
    # `gh run download` fails when nothing matches, and the callers rely on that.
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
