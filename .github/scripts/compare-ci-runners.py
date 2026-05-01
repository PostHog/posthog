#!/usr/bin/env python3
# ruff: noqa: T201 print is the intended output of this CLI
# Pair Depot and Blacksmith job durations for the 7-day CI trial.
#
# Usage:
#   python3 .github/scripts/compare-ci-runners.py --days 7 > report.md
#   python3 .github/scripts/compare-ci-runners.py --since 2026-04-20T18:00:00Z --until 2026-04-21T10:30:00Z > report.md
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
import time
import argparse
import statistics
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


DEFAULT_CACHE_DIR = Path(".cache/compare-ci-runners")
SKIPPED_RUN_CONCLUSIONS = {"skipped", "cancelled", "action_required"}


def is_retryable_gh_error(stderr: str) -> bool:
    return "HTTP 5" in stderr or "Server Error" in stderr or "connection reset" in stderr


def run_gh(args: list[str], attempts: int = 3) -> str:
    for attempt in range(1, attempts + 1):
        try:
            r = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
            return r.stdout
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            if attempt < attempts and is_retryable_gh_error(stderr):
                time.sleep(2 * attempt)
                continue
            if stderr:
                print(stderr.strip(), file=sys.stderr)
            raise
    raise RuntimeError("unreachable")


def parse_utc_datetime(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"invalid datetime: {value}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def created_dates(since: datetime, until: datetime) -> list[str]:
    day = since.date()
    last_day = until.date()
    dates = []
    while day <= last_day:
        dates.append(day.isoformat())
        day += timedelta(days=1)
    return dates


def safe_cache_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def load_cached_run_list(cache_dir: Path, workflow: str, created: str) -> list[dict] | None:
    cache_path = cache_dir / "runs" / f"{safe_cache_key(workflow)}-{created}.json"
    try:
        return json.loads(cache_path.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def save_cached_run_list(cache_dir: Path, workflow: str, created: str, runs: list[dict]) -> None:
    cache_path = cache_dir / "runs" / f"{safe_cache_key(workflow)}-{created}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(runs, sort_keys=True))


def list_runs_for_date(workflow: str, created: str, cache_dir: Path, use_cache: bool) -> tuple[list[dict], bool]:
    if use_cache:
        cached_runs = load_cached_run_list(cache_dir, workflow, created)
        if cached_runs is not None:
            return cached_runs, True
    out = run_gh(
        [
            "run",
            "list",
            "--workflow",
            workflow,
            "--created",
            created,
            "-L",
            "1000",
            "--json",
            "databaseId,headSha,createdAt,conclusion,event",
        ]
    )
    runs = json.loads(out)
    if use_cache:
        save_cached_run_list(cache_dir, workflow, created, runs)
    return runs, False


def list_recent_runs(
    workflow: str,
    since: datetime,
    until: datetime,
    include_cancelled: bool,
    cache_dir: Path,
    use_cache: bool,
) -> tuple[list[dict], dict[str, int], dict[str, int]]:
    # Use GitHub's created filter to avoid walking unrelated pages, then apply
    # exact timestamp bounds locally because --created is day-granular here.
    runs_by_id: dict[int, dict] = {}
    skipped_by_conclusion: dict[str, int] = defaultdict(int)
    cache_stats = {"run_list_cache_hits": 0, "run_list_api_fetches": 0}
    allowed_skipped_conclusions = SKIPPED_RUN_CONCLUSIONS - ({"cancelled"} if include_cancelled else set())
    for created in created_dates(since, until):
        runs, from_cache = list_runs_for_date(workflow, created, cache_dir, use_cache)
        cache_stats["run_list_cache_hits" if from_cache else "run_list_api_fetches"] += 1
        for r in runs:
            run_id = r.get("databaseId")
            if not run_id or run_id in runs_by_id:
                continue
            try:
                ts = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
            except Exception:
                continue
            if ts < since or ts > until:
                continue
            conclusion = r.get("conclusion") or "unknown"
            if conclusion in allowed_skipped_conclusions:
                skipped_by_conclusion[conclusion] += 1
                continue
            runs_by_id[run_id] = r
    return list(runs_by_id.values()), dict(skipped_by_conclusion), cache_stats


def load_cached_jobs(cache_dir: Path, run_id: int) -> list[dict] | None:
    cache_path = cache_dir / "jobs" / f"{run_id}.json"
    try:
        return json.loads(cache_path.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def save_cached_jobs(cache_dir: Path, run_id: int, jobs: list[dict]) -> None:
    cache_path = cache_dir / "jobs" / f"{run_id}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(jobs, sort_keys=True))


def get_jobs(run_id: int, repo: str, cache_dir: Path, use_cache: bool) -> tuple[list[dict], bool]:
    if use_cache:
        cached_jobs = load_cached_jobs(cache_dir, run_id)
        if cached_jobs is not None:
            return cached_jobs, True
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
    if use_cache:
        save_cached_jobs(cache_dir, run_id, jobs)
    return jobs, False


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


def collect_jobs_for_runs(
    runs: list[dict], repo: str, cache_dir: Path, use_cache: bool, workers: int
) -> tuple[list[tuple[dict, list[dict]]], dict[str, int]]:
    stats = {"cache_hits": 0, "api_fetches": 0, "errors": 0}
    if not runs:
        return [], stats

    results: list[tuple[dict, list[dict]]] = []
    max_workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(get_jobs, run["databaseId"], repo, cache_dir, use_cache): run for run in runs}
        for future in as_completed(futures):
            run = futures[future]
            try:
                jobs, from_cache = future.result()
            except subprocess.CalledProcessError:
                stats["errors"] += 1
                continue
            stats["cache_hits" if from_cache else "api_fetches"] += 1
            results.append((run, jobs))
    return results, stats


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
    ap.add_argument("--since", type=parse_utc_datetime)
    ap.add_argument("--until", type=parse_utc_datetime)
    ap.add_argument("--format", choices=["md", "csv"], default="md")
    ap.add_argument("--repo", help="GitHub repo in OWNER/REPO form. Defaults to gh's current repo.")
    ap.add_argument(
        "--workflow",
        action="append",
        dest="workflows",
        help="Workflow file to include. Can be passed multiple times. Defaults to all tracked workflows.",
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument(
        "--include-cancelled",
        action="store_true",
        help="Fetch jobs for cancelled workflow runs. Useful for forensics, but noisy for runner comparison.",
    )
    args = ap.parse_args()
    if args.until and not args.since:
        ap.error("--until requires --since")

    repo = args.repo or get_repo()
    until = args.until or datetime.now(UTC)
    since = args.since or (until - timedelta(days=args.days))
    if since > until:
        ap.error("--since must be before --until")
    use_cache = not args.no_cache
    print(f"# Collecting jobs from {repo} from {since.isoformat()} through {until.isoformat()}", file=sys.stderr)

    # observations[(workflow, base_name)][sha][provider] = {"sec": dur, "conclusion": conc}
    observations: dict[tuple[str, str], dict[str, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    total_runs = total_cache_hits = total_api_fetches = total_errors = 0
    total_run_list_cache_hits = total_run_list_api_fetches = 0
    total_skipped_by_conclusion: dict[str, int] = defaultdict(int)

    workflows = args.workflows or WORKFLOWS
    for wf in workflows:
        print(f"# {wf}", file=sys.stderr)
        try:
            runs, skipped_by_conclusion, run_list_stats = list_recent_runs(
                wf, since, until, args.include_cancelled, args.cache_dir, use_cache
            )
        except subprocess.CalledProcessError as e:
            print(f"  SKIP ({e})", file=sys.stderr)
            continue
        total_run_list_cache_hits += run_list_stats["run_list_cache_hits"]
        total_run_list_api_fetches += run_list_stats["run_list_api_fetches"]
        for conclusion, count in skipped_by_conclusion.items():
            total_skipped_by_conclusion[conclusion] += count
        total_runs += len(runs)
        run_jobs, fetch_stats = collect_jobs_for_runs(runs, repo, args.cache_dir, use_cache, args.workers)
        total_cache_hits += fetch_stats["cache_hits"]
        total_api_fetches += fetch_stats["api_fetches"]
        total_errors += fetch_stats["errors"]
        print(
            f"  runs={len(runs)} run_list_cache_hits={run_list_stats['run_list_cache_hits']} "
            f"run_list_api_fetches={run_list_stats['run_list_api_fetches']} "
            f"job_cache_hits={fetch_stats['cache_hits']} job_api_fetches={fetch_stats['api_fetches']} "
            f"errors={fetch_stats['errors']}",
            file=sys.stderr,
        )
        for run, jobs in run_jobs:
            sha = run["headSha"]
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
    skipped_summary = ", ".join(
        f"{conclusion}={count}" for conclusion, count in sorted(total_skipped_by_conclusion.items())
    )
    print(
        "# Summary: "
        f"runs_fetched={total_runs} run_list_cache_hits={total_run_list_cache_hits} "
        f"run_list_api_fetches={total_run_list_api_fetches} job_cache_hits={total_cache_hits} "
        f"job_api_fetches={total_api_fetches} "
        f"errors={total_errors} skipped_before_jobs=({skipped_summary or 'none'})",
        file=sys.stderr,
    )

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
    print(f"\nCollection window: `{since.isoformat()}` through `{until.isoformat()}`. Repo: `{repo}`.\n")
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
