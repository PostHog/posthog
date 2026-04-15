#!/usr/bin/env python3
# ruff: noqa: T201 print is the intended output of this CLI
# Pair Depot and Blacksmith job durations for the 7-day CI trial.
#
# Usage:
#   python3 .github/scripts/compare-ci-runners.py --days 7 > report.md
#   python3 .github/scripts/compare-ci-runners.py --days 7 --format csv > pairs.csv
#
# Requires: `gh` CLI authenticated, `jq` not required (we parse JSON in Python).
# Pulls jobs for listed workflows, groups by (workflow, base_job_name, sha),
# splits each group into depot-runner vs blacksmith-runner, reports paired deltas.
#
# How pairing works:
#   - Matrix-expanded jobs have names like "Python code quality (depot-ubuntu-latest)"
#     and "Python code quality (blacksmith-2vcpu-ubuntu-2404)". Base name stripped
#     by removing trailing " (<runner>)".
#   - Dedicated shadow jobs use the suffix "-blacksmith" or "blacksmith shadow" in name.
#   - Pairs: same (workflow, base_name, sha) → one depot duration + one blacksmith duration.

import re
import sys
import json
import argparse
import statistics
import subprocess
from collections import defaultdict
from datetime import UTC, datetime, timedelta

WORKFLOWS = [
    "ci-backend.yml",
    "ci-dagster.yml",
    "ci-e2e-playwright.yml",
    "ci-mcp.yml",
    "ci-nodejs.yml",
    "ci-proto.yml",
    "ci-python.yml",
    "ci-rust-flags-integration.yml",
    "ci-rust.yml",
    "ci-storybook.yml",
    "ci-blacksmith-shadow.yml",
]

RUNNER_LABEL_RE = re.compile(r"\s*\((depot-[a-z0-9.-]+|blacksmith-[a-z0-9.-]+)\)\s*$")


def run_gh(args: list[str]) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return r.stdout


def list_recent_runs(workflow: str, since: datetime) -> list[dict]:
    # gh run list --workflow <w> -L 1000 --json databaseId,headSha,createdAt,conclusion,event
    out = run_gh(
        [
            "run",
            "list",
            "--workflow",
            workflow,
            "-L",
            "10",
            "--json",
            "databaseId,headSha,createdAt,conclusion,event",
        ]
    )
    runs = json.loads(out)
    filtered = []
    for r in runs:
        try:
            ts = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < since:
            continue
        filtered.append(r)
    return filtered


def get_jobs(run_id: int, repo: str) -> list[dict]:
    out = run_gh(
        [
            "api",
            "--paginate",
            f"repos/{repo}/actions/runs/{run_id}/jobs",
            "--jq",
            ".jobs[] | {name, started_at, completed_at, conclusion}",
        ]
    )
    jobs = []
    for line in out.strip().splitlines():
        if not line:
            continue
        jobs.append(json.loads(line))
    return jobs


def classify_runner(job_name: str) -> tuple[str, str]:
    """
    Returns (base_name, runner_provider). runner_provider is 'depot', 'blacksmith',
    or 'unknown'. base_name strips the trailing runner label if present, or the
    'blacksmith shadow' / '-blacksmith' marker.
    """
    # Matrix-expanded form: "Name (depot-foo)" or "Name (blacksmith-foo)"
    m = RUNNER_LABEL_RE.search(job_name)
    if m:
        provider = "depot" if m.group(1).startswith("depot") else "blacksmith"
        base = job_name[: m.start()].rstrip()
        return base, provider

    # Dedicated shadow form: "... (blacksmith shadow ...)" or "...-blacksmith"
    if "blacksmith shadow" in job_name.lower():
        base = re.sub(r"\s*\(blacksmith shadow[^)]*\)\s*", "", job_name).strip()
        return base, "blacksmith"
    if job_name.endswith("-blacksmith"):
        return job_name[: -len("-blacksmith")], "blacksmith"

    # Assume depot (original, non-shadow) if the workflow is on our list
    return job_name, "depot"


def duration_seconds(started: str, completed: str) -> float | None:
    if not started or not completed:
        return None
    try:
        s = datetime.fromisoformat(started.replace("Z", "+00:00"))
        c = datetime.fromisoformat(completed.replace("Z", "+00:00"))
        return (c - s).total_seconds()
    except Exception:
        return None


def get_repo() -> str:
    out = run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    return out.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--format", choices=["md", "csv"], default="md")
    args = ap.parse_args()

    repo = get_repo()
    since = datetime.now(UTC) - timedelta(days=args.days)
    print(f"# Collecting jobs from {repo} since {since.date()}", file=sys.stderr)

    # pairs[(workflow, base_name)] = list of {sha, depot_sec, blacksmith_sec}
    pairs: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for wf in WORKFLOWS:
        print(f"# {wf}", file=sys.stderr)
        try:
            runs = list_recent_runs(wf, since)
        except subprocess.CalledProcessError as e:
            print(f"  SKIP ({e})", file=sys.stderr)
            continue
        for run in runs:
            rid = run["databaseId"]
            sha = run["headSha"]
            try:
                jobs = get_jobs(rid, repo)
            except subprocess.CalledProcessError:
                continue
            # Collect per-base-name entries for this run
            by_base: dict[str, dict] = defaultdict(dict)
            for j in jobs:
                base, provider = classify_runner(j["name"])
                dur = duration_seconds(j["started_at"], j["completed_at"])
                if dur is None:
                    continue
                if j["conclusion"] not in ("success", "failure"):
                    continue  # skipped/cancelled not useful
                by_base[base][f"{provider}_sec"] = dur
                by_base[base][f"{provider}_conclusion"] = j["conclusion"]
            for base, entry in by_base.items():
                if "depot_sec" in entry and "blacksmith_sec" in entry:
                    pairs[(wf, base)].append({"sha": sha, **entry})

    if args.format == "csv":
        print("workflow,job,sha,depot_sec,blacksmith_sec,delta_sec,speedup")
        for (wf, base), rows in sorted(pairs.items()):
            for r in rows:
                d, b = r["depot_sec"], r["blacksmith_sec"]
                print(f'"{wf}","{base}",{r["sha"]},{d:.1f},{b:.1f},{d - b:.1f},{d / b:.2f}')
        return

    # Markdown summary
    print("# Blacksmith vs Depot — paired CI job durations")
    print(f"\nCollection window: last {args.days} days. Repo: `{repo}`.\n")
    print(
        "Each row is an `(workflow, job)` for which we have at least one paired run (same SHA produced both a Depot and a Blacksmith result). Durations are seconds.\n"
    )
    print(
        "| Workflow | Job | Pairs | Depot median | Blacksmith median | Speedup (median) | Depot p95 | Blacksmith p95 |"
    )
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    summary_rows = []
    for (wf, base), rows in sorted(pairs.items()):
        depot = [r["depot_sec"] for r in rows]
        bs = [r["blacksmith_sec"] for r in rows]
        dm = statistics.median(depot)
        bm = statistics.median(bs)
        speedup = dm / bm if bm > 0 else float("inf")
        dp95 = sorted(depot)[max(0, int(len(depot) * 0.95) - 1)]
        bp95 = sorted(bs)[max(0, int(len(bs) * 0.95) - 1)]
        summary_rows.append((speedup, wf, base, len(rows), dm, bm, dp95, bp95))

    # Sort by speedup descending — biggest wins at the top
    for speedup, wf, base, n, dm, bm, dp95, bp95 in sorted(summary_rows, reverse=True):
        print(f"| `{wf}` | {base} | {n} | {dm:.0f}s | {bm:.0f}s | **{speedup:.2f}x** | {dp95:.0f}s | {bp95:.0f}s |")

    print("\n## Interpretation")
    print(
        "- **Speedup > 1.0** → Blacksmith is faster on that job\n"
        "- **Speedup < 1.0** → Blacksmith is slower (decision: is the price cut worth it?)\n"
        "- Low `Pairs` count (< 10) → treat as noisy; widen window or re-run\n"
        "- Compare `p95` to `median` — a large gap means runner variance is high\n"
    )


if __name__ == "__main__":
    main()
