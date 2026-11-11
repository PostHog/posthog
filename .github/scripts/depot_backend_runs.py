#!/usr/bin/env python3
"""Read the master Backend CI runs on Depot CI: their verdicts and their artifacts.

The master push and the hourly run of Backend CI live on Depot CI, which keeps its runs and
artifacts apart from GitHub Actions. This is the Depot counterpart of listing workflow runs
with `gh api` and fetching artifacts with `gh run download`.

    depot_backend_runs.py find --trigger schedule --prefix timing_data- --min-artifacts 38 --limit 5
    depot_backend_runs.py download <run-id> --pattern 'timing_data-Core-*' --dir timing
    depot_backend_runs.py gate-runs --trigger push --limit 40 --out runs.json

`find` prints one `<run-id> <sha>` line per run of the trigger with the artifacts, newest first;
it lists successful runs unless `--status` says otherwise.
`download` unpacks each matching artifact into `<dir>/<artifact name>/`, the layout
`gh run download` produces. `gate-runs` writes the newest runs of one trigger as JSON, each
with the conclusion of its gate job, in the shape .github/scripts/ci-alerts-devex.js reads
GitHub workflow runs in.
Needs the `depot` CLI and DEPOT_TOKEN. Reading push runs also needs the `gh` CLI and a GitHub token.
"""

from __future__ import annotations

import re
import sys
import json
import time
import fnmatch
import zipfile
import argparse
import tempfile
import subprocess
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict, cast

REPO = "PostHog/posthog"
WORKFLOW_NAME = "Backend CI on Depot"
GATE_JOB_KEY = "ci-backend.yml:django_tests"
GATE_CONCLUSIONS = {"finished": "success", "failed": "failure", "cancelled": "cancelled"}
ENDED = frozenset(GATE_CONCLUSIONS)
# Short enough that the alerter's lane reads end inside their step timeout.
CLI_TIMEOUT_SECONDS = 10
DOWNLOAD_TIMEOUT_SECONDS = 120
PARALLEL_CLI_CALLS = 8
# The Depot CLI returns at most 200 workflows, which is 8 days of hourly runs.
MAX_LISTED = 200
TRIGGERS = ("push", "schedule")
MASTER_REF = "refs/heads/master"
# Master is the compare base, so these statuses mean master contains the commit.
ON_MASTER_STATUSES = frozenset({"BEHIND", "IDENTICAL"})
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
GITHUB_TIMEOUT_SECONDS = 30


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


def commits_on_master(shas: Iterable[str], repo: str = REPO) -> frozenset[str]:
    """A commit GitHub cannot resolve fails the whole query."""
    candidates = sorted({sha for sha in shas if COMMIT_SHA.fullmatch(sha)})
    if not candidates:
        return frozenset()
    owner, name = repo.split("/")
    # Without headTarget, GitHub answers IDENTICAL for a commit it does not have.
    fields = " ".join(
        f'c{i}: compare(headRef: "{sha}") {{ status headTarget {{ oid }} }}' for i, sha in enumerate(candidates)
    )
    query = (
        f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) "
        f'{{ ref(qualifiedName: "{MASTER_REF}") {{ {fields} }} }} }}'
    )
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        timeout=GITHUB_TIMEOUT_SECONDS,
    )
    compared = json.loads(result.stdout)["data"]["repository"]["ref"]
    return frozenset(
        sha
        for i, sha in enumerate(candidates)
        if (comparison := compared.get(f"c{i}"))
        and comparison["status"] in ON_MASTER_STATUSES
        and comparison["headTarget"]["oid"] == sha
    )


def listed_workflows(statuses: list[str], limit: int, *, trigger: str, repo: str = REPO) -> list[ListedWorkflow]:
    args = ["workflow", "list", "--repo", repo, "--name", WORKFLOW_NAME, "--trigger", trigger, "-n", str(limit)]
    for status in statuses:
        args += ["--status", status]
    # The CLI prints `null` when nothing matches.
    try:
        output = depot(*args, "--output", "json")
    except subprocess.TimeoutExpired:
        output = depot(*args, "--output", "json")
    workflows = cast(list[ListedWorkflow], json.loads(output or "null") or [])
    return sorted(workflows, key=lambda w: w["created_at"], reverse=True)


def master_only(workflows: list[ListedWorkflow], *, trigger: str, repo: str = REPO) -> list[ListedWorkflow]:
    """A branch can add itself to the push trigger in its own copy of the workflow, and Depot
    records a push run's ref as its sha, so only GitHub can say a push ran on master.
    """
    if trigger == "schedule":
        return workflows
    on_master = commits_on_master((w["sha"] for w in workflows), repo)
    return [w for w in workflows if w["sha"] in on_master]


def master_workflows(statuses: list[str], limit: int, *, trigger: str, repo: str = REPO) -> list[ListedWorkflow]:
    """The master Backend CI workflows of one trigger in the given states, newest first."""
    return master_only(listed_workflows(statuses, limit, trigger=trigger, repo=repo), trigger=trigger, repo=repo)


def show(workflow_id: str) -> ShownWorkflow:
    return cast(ShownWorkflow, json.loads(depot("workflow", "show", workflow_id, "--output", "json")))


def artifacts(run_id: str) -> list[Artifact]:
    listed = json.loads(depot("artifacts", "list", run_id, "--output", "json") or "null") or {}
    return cast(list[Artifact], listed.get("artifacts") or [])


def newest_per_name(run_artifacts: list[Artifact]) -> list[Artifact]:
    """A retried job uploads its artifact again under the same name. Keep the newest."""
    newest: dict[str, Artifact] = {}
    for artifact in sorted(run_artifacts, key=lambda a: a["created_at"]):
        newest[artifact["name"]] = artifact
    return list(newest.values())


def find(
    prefix: str, min_artifacts: int, limit: int, max_age_days: int, *, trigger: str, statuses: list[str]
) -> list[ListedWorkflow]:
    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: list[ListedWorkflow] = []
    for workflow in master_workflows(statuses, MAX_LISTED, trigger=trigger):
        if workflow["created_at"] < cutoff:
            break
        try:
            names = {a["name"] for a in artifacts(workflow["run_id"]) if a["name"].startswith(prefix)}
            sys.stderr.write(f"Run {workflow['run_id']} has {len(names)} {prefix}* artifacts\n")
        except (subprocess.SubprocessError, json.JSONDecodeError) as error:
            sys.stderr.write(f"Run {workflow['run_id']}: could not read it, skipping it: {error!r}\n")
            continue
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
    shown = show(listed["workflow_id"])
    gate = next((job for job in shown.get("jobs") or [] if job.get("job_key") == GATE_JOB_KEY), None)
    conclusion: str | None = None
    if gate and gate.get("status") in GATE_CONCLUSIONS:
        conclusion = GATE_CONCLUSIONS[gate["status"]]
    elif listed["status"] in ENDED:
        # A run that ended without a gate verdict ran no checks. The alerter drops skipped
        # runs, so reporting one as skipped would hide a lane that tests nothing.
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


def gate_runs(trigger: str, limit: int) -> list[GateRun]:
    listed = master_workflows(["queued", "running", *sorted(ENDED)], limit, trigger=trigger)
    with ThreadPoolExecutor(max_workers=PARALLEL_CLI_CALLS) as pool:
        runs = list(pool.map(gate_run, listed))
    # An empty or inconclusive window must not resolve an existing CI incident.
    if not any(
        run["status"] == "completed" and run["conclusion"] not in (None, "cancelled", "skipped") for run in runs
    ):
        raise ValueError(f"No settled Backend CI verdict in the {trigger} run window")
    return runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    find_parser = commands.add_parser("find")
    find_parser.add_argument("--trigger", choices=TRIGGERS, required=True)
    find_parser.add_argument("--prefix", required=True)
    find_parser.add_argument("--min-artifacts", type=int, default=1)
    find_parser.add_argument("--limit", type=int, default=1)
    find_parser.add_argument("--max-age-days", type=int, default=14)
    # A run whose unrelated job failed after the upload still carries the artifact.
    find_parser.add_argument("--status", action="append", choices=sorted(ENDED), default=None)
    download_parser = commands.add_parser("download")
    download_parser.add_argument("run_id")
    download_parser.add_argument("--pattern", action="append", required=True)
    download_parser.add_argument("--dir", type=Path, required=True)
    gate_parser = commands.add_parser("gate-runs")
    gate_parser.add_argument("--trigger", choices=TRIGGERS, required=True)
    gate_parser.add_argument("--limit", type=int, required=True)
    gate_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "find":
        for workflow in find(
            args.prefix,
            args.min_artifacts,
            args.limit,
            args.max_age_days,
            trigger=args.trigger,
            statuses=args.status or ["finished"],
        ):
            sys.stdout.write(f"{workflow['run_id']} {workflow['sha']}\n")
        return 0
    if args.command == "gate-runs":
        # Written whole, so a reader never sees a half-written file.
        partial = args.out.with_suffix(".partial")
        partial.write_text(json.dumps(gate_runs(args.trigger, args.limit)))
        partial.replace(args.out)
        return 0
    count = download(args.run_id, args.pattern, args.dir)
    sys.stderr.write(f"Downloaded {count} artifacts matching {args.pattern} from run {args.run_id}\n")
    # `gh run download` fails when nothing matches, and the callers rely on that.
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
