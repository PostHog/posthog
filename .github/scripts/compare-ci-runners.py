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
#
# Conclusions:
#   - Speedup uses only success↔success pairs (mixed conclusions would be apples-to-oranges).
#   - Failure rates are tracked per runner across ALL observed runs (paired or not).
#   - Singletons (runs that only appeared on one runner for a given SHA) are reported separately.

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

# Matches a runner label at the end of a job name, either alone in trailing parens
# ("Name (depot-foo)") or as the last comma-separated item ("Name (1/3, depot-foo)").
# The optional prefix group lets us keep shard/group context so matrix jobs that mix
# shard and runner in the same parens still pair across providers.
RUNNER_LABEL_RE = re.compile(
    r"\s*\((?:(?P<prefix>[^()]*?),\s*)?(?P<runner>depot-[a-z0-9.-]+|blacksmith-[a-z0-9.-]+)\s*\)\s*$"
)


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
            "1000",
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
            "--slurp",
            f"repos/{repo}/actions/runs/{run_id}/jobs",
        ]
    )
    pages = json.loads(out)
    jobs = []
    for page in pages:
        for j in page.get("jobs", []):
            jobs.append(
                {
                    "name": j.get("name"),
                    "started_at": j.get("started_at"),
                    "completed_at": j.get("completed_at"),
                    "conclusion": j.get("conclusion"),
                }
            )
    return jobs


def classify_runner(job_name: str) -> tuple[str, str]:
    """
    Returns (base_name, runner_provider). runner_provider is 'depot', 'blacksmith',
    or 'unknown'. base_name strips the trailing runner label if present, or the
    'blacksmith shadow' / '-blacksmith' marker.
    """
    # Matrix-expanded form: "Name (depot-foo)", "Name (blacksmith-foo)", or the
    # mixed form "Name (1/3, depot-foo)" where runner shares parens with shard/group.
    m = RUNNER_LABEL_RE.search(job_name)
    if m:
        provider = "depot" if m.group("runner").startswith("depot") else "blacksmith"
        prefix = m.group("prefix")
        head = job_name[: m.start()].rstrip()
        # Preserve non-runner parens content (e.g. shard) so depot and blacksmith
        # variants collapse to the same base name.
        base = f"{head} ({prefix.strip()})" if prefix is not None else head
        return base, provider

    # Dedicated shadow form: "... (blacksmith shadow ...)" or "...-blacksmith"
    if "blacksmith shadow" in job_name.lower():
        base = re.sub(r"\s*\(blacksmith shadow[^)]*\)\s*", "", job_name).strip()
        return base, "blacksmith"
    if job_name.endswith("-blacksmith"):
        return job_name[: -len("-blacksmith")], "blacksmith"

    # Unrecognized job naming should not be attributed to either provider.
    return job_name, "unknown"


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


def derive_stats(by_sha: dict[str, dict[str, dict]]) -> dict:
    """Reduce a (wf, base) sha→provider→{sec,conclusion} map into summary stats."""
    depot_total = depot_fail = 0
    bs_total = bs_fail = 0
    success_pairs: list[tuple[float, float]] = []
    mixed_pairs = 0
    depot_only = bs_only = 0
    for providers in by_sha.values():
        d = providers.get("depot")
        b = providers.get("blacksmith")
        if d:
            depot_total += 1
            if d["conclusion"] == "failure":
                depot_fail += 1
        if b:
            bs_total += 1
            if b["conclusion"] == "failure":
                bs_fail += 1
        if d and b:
            if d["conclusion"] == "success" and b["conclusion"] == "success":
                success_pairs.append((d["sec"], b["sec"]))
            else:
                mixed_pairs += 1
        elif d:
            depot_only += 1
        elif b:
            bs_only += 1
    return {
        "depot_total": depot_total,
        "depot_fail": depot_fail,
        "bs_total": bs_total,
        "bs_fail": bs_fail,
        "success_pairs": success_pairs,
        "mixed_pairs": mixed_pairs,
        "depot_only": depot_only,
        "bs_only": bs_only,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--format", choices=["md", "csv"], default="md")
    args = ap.parse_args()

    repo = get_repo()
    since = datetime.now(UTC) - timedelta(days=args.days)
    print(f"# Collecting jobs from {repo} since {since.date()}", file=sys.stderr)

    # observations[(workflow, base_name)][sha][provider] = {"sec": dur, "conclusion": conc}
    observations: dict[tuple[str, str], dict[str, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))

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
            for j in jobs:
                base, provider = classify_runner(j["name"])
                dur = duration_seconds(j["started_at"], j["completed_at"])
                if dur is None:
                    continue
                if j["conclusion"] not in ("success", "failure"):
                    continue  # skipped/cancelled not useful
                observations[(wf, base)][sha][provider] = {
                    "sec": dur,
                    "conclusion": j["conclusion"],
                }

    if args.format == "csv":
        print("workflow,job,sha,depot_sec,blacksmith_sec,depot_conclusion,blacksmith_conclusion,delta_sec,speedup")
        for (wf, base), by_sha in sorted(observations.items()):
            for sha, providers in by_sha.items():
                d = providers.get("depot")
                b = providers.get("blacksmith")
                d_sec = f"{d['sec']:.1f}" if d else ""
                b_sec = f"{b['sec']:.1f}" if b else ""
                d_conc = d["conclusion"] if d else ""
                b_conc = b["conclusion"] if b else ""
                if d and b and d["conclusion"] == "success" and b["conclusion"] == "success" and b["sec"] > 0:
                    delta = f"{d['sec'] - b['sec']:.1f}"
                    speedup = f"{d['sec'] / b['sec']:.2f}"
                else:
                    delta = ""
                    speedup = ""
                print(f'"{wf}","{base}",{sha},{d_sec},{b_sec},{d_conc},{b_conc},{delta},{speedup}')
        return

    # Markdown summary
    print("# Blacksmith vs Depot — paired CI job durations")
    print(f"\nCollection window: last {args.days} days. Repo: `{repo}`.\n")
    print(
        "Each row is an `(workflow, job)` with at least one same-SHA success↔success pair. "
        "**Speedup uses success↔success pairs only** — mixed-conclusion pairs are counted in `Mixed` but excluded from the ratio. "
        "`Fails` is the per-runner failure count across all observed runs (paired or not). Durations are seconds.\n"
    )
    print(
        "| Workflow | Job | Success pairs | Depot median | Blacksmith median | Speedup (median) | Depot p95 | Blacksmith p95 | Depot fails | Blacksmith fails | Mixed |"
    )
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    summary_rows = []
    stats_by_key: dict[tuple[str, str], dict] = {}
    for (wf, base), by_sha in sorted(observations.items()):
        s = derive_stats(by_sha)
        stats_by_key[(wf, base)] = s
        if not s["success_pairs"]:
            continue  # no comparable data — surfaced in singletons table below
        depot = [p[0] for p in s["success_pairs"]]
        bs = [p[1] for p in s["success_pairs"]]
        dm = statistics.median(depot)
        bm = statistics.median(bs)
        speedup = dm / bm if bm > 0 else float("inf")
        dp95 = sorted(depot)[max(0, int(len(depot) * 0.95) - 1)]
        bp95 = sorted(bs)[max(0, int(len(bs) * 0.95) - 1)]
        dfail = f"{s['depot_fail']}/{s['depot_total']}"
        bfail = f"{s['bs_fail']}/{s['bs_total']}"
        summary_rows.append(
            (speedup, wf, base, len(s["success_pairs"]), dm, bm, dp95, bp95, dfail, bfail, s["mixed_pairs"])
        )

    # Sort by speedup descending — biggest wins at the top
    for speedup, wf, base, n, dm, bm, dp95, bp95, dfail, bfail, mixed in sorted(summary_rows, reverse=True):
        print(
            f"| `{wf}` | {base} | {n} | {dm:.0f}s | {bm:.0f}s | **{speedup:.2f}x** | "
            f"{dp95:.0f}s | {bp95:.0f}s | {dfail} | {bfail} | {mixed} |"
        )

    # Unpaired / singleton jobs — highlights where the shadow didn't fire consistently
    unpaired_rows = [
        (wf, base, s["depot_only"], s["bs_only"])
        for (wf, base), s in sorted(stats_by_key.items())
        if s["depot_only"] or s["bs_only"]
    ]
    if unpaired_rows:
        print("\n## Unpaired runs")
        print(
            "Jobs that ran on only one runner for a given SHA (shadow didn't fire, paths filter "
            "differed, job was skipped on the other side, etc.). Large imbalances mean the "
            "pairing denominator above is small.\n"
        )
        print("| Workflow | Job | Depot-only | Blacksmith-only |")
        print("| --- | --- | ---: | ---: |")
        for wf, base, d_only, b_only in unpaired_rows:
            print(f"| `{wf}` | {base} | {d_only} | {b_only} |")

    print("\n## Interpretation")
    print(
        "- **Speedup > 1.0** → Blacksmith is faster on that job\n"
        "- **Speedup < 1.0** → Blacksmith is slower (decision: is the price cut worth it?)\n"
        "- **Fails (x/y)** → per-runner failure count across all observed runs. High asymmetry "
        "(e.g. `5/50` vs `1/50`) points to runner-specific instability\n"
        "- **Mixed** → pairs where one runner passed and the other failed. Excluded from speedup "
        "but worth inspecting manually — the shadow may be masking a flake or a real break\n"
        "- Low `Success pairs` count (< 10) → treat as noisy; widen window or re-run\n"
        "- Compare `p95` to `median` — a large gap means runner variance is high\n"
    )


if __name__ == "__main__":
    main()
