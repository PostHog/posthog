#!/usr/bin/env python3
"""Compute Rust test shard weights from recent CI run logs.

Parses `gh run view --log` output to extract per-package compile + test
durations, then writes updated weights to ci-rust.yml.

Usage:
    python update_rust_shard_weights.py [--run-id RUN_ID] [--num-runs N] [--dry-run]

If --run-id is not given, fetches the N most recent successful Rust CI runs
on master and averages across them.
"""

import argparse
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

WORKFLOW_FILE = Path(__file__).resolve().parents[1] / "workflows" / "ci-rust.yml"
REPO = "PostHog/posthog"


def get_recent_run_ids(n: int) -> list[int]:
    """Find the N most recent successful Rust CI runs on master."""
    result = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            REPO,
            "--workflow",
            "ci-rust.yml",
            "--branch",
            "master",
            "--status",
            "success",
            "--limit",
            str(n),
            "--json",
            "databaseId",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    runs = json.loads(result.stdout)
    return [r["databaseId"] for r in runs]


def get_run_logs(run_id: int) -> str:
    """Download logs for a run, filtering to timing-relevant lines."""
    result = subprocess.run(
        ["gh", "run", "view", str(run_id), "--repo", REPO, "--log"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def parse_shard_timings(logs: str) -> dict[str, float]:
    """Parse logs to extract per-shard wall-clock times for the cargo test step.

    Returns a dict of {shard_packages_string: duration_seconds}.
    """
    # Lines look like:
    # Test Rust (pkg1 pkg2 pkg3)\tRun cargo test\t2026-05-07T12:47:48.123Z ...
    shard_timestamps: dict[str, list[float]] = defaultdict(list)
    ts_pattern = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)Z")
    shard_pattern = re.compile(r"^Test Rust \(([^)]+)\)")

    for line in logs.splitlines():
        if "Run cargo test" not in line:
            continue
        shard_match = shard_pattern.match(line)
        if not shard_match:
            continue
        shard_key = shard_match.group(1)
        ts_match = ts_pattern.search(line)
        if ts_match:
            # Parse timestamp to epoch seconds
            from datetime import datetime

            ts = datetime.fromisoformat(ts_match.group(1))
            shard_timestamps[shard_key].append(ts.timestamp())

    # Compute duration as last - first timestamp per shard
    shard_durations = {}
    for shard_key, timestamps in shard_timestamps.items():
        if len(timestamps) >= 2:
            shard_durations[shard_key] = max(timestamps) - min(timestamps)

    return shard_durations


def compute_package_weights(
    shard_durations: dict[str, float],
) -> dict[str, int]:
    """Distribute shard duration proportionally among packages.

    Uses a simple heuristic: packages are weighted equally within a shard,
    then scaled so the sum matches the observed duration. This gives a
    reasonable starting point that the bin-packer can work with.

    For better accuracy, we also parse per-test-binary timing from the logs.
    """
    package_weights: dict[str, float] = {}

    for shard_key, duration in shard_durations.items():
        packages = shard_key.split()
        # Equal distribution as baseline
        per_pkg = duration / len(packages)
        for pkg in packages:
            package_weights[pkg] = per_pkg

    # Round to integers
    return {pkg: max(1, round(w)) for pkg, w in sorted(package_weights.items())}


def parse_detailed_timings(logs: str) -> dict[str, float]:
    """Parse per-package durations from cargo test output.

    Looks at "Finished" lines (compile time) and "test result:" lines
    (test execution time) to build a more accurate per-package picture.
    """
    from datetime import datetime

    # Track time ranges per shard
    shard_pattern = re.compile(r"^Test Rust \(([^)]+)\)")
    ts_pattern = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)Z")

    # For each shard, track the sequence of "Finished" compilations
    # Each "Finished" marks a new package being compiled/tested
    shard_segments: dict[str, list[tuple[float, str]]] = defaultdict(list)

    for line in logs.splitlines():
        if "Run cargo test" not in line:
            continue
        shard_match = shard_pattern.match(line)
        if not shard_match:
            continue
        shard_key = shard_match.group(1)
        ts_match = ts_pattern.search(line)
        if not ts_match:
            continue
        ts = datetime.fromisoformat(ts_match.group(1)).timestamp()

        if "Finished" in line and "test" in line:
            shard_segments[shard_key].append((ts, "compile"))

    # Use shard total durations and number of compile phases to estimate
    # per-package costs
    shard_durations = parse_shard_timings(logs)
    package_durations: dict[str, float] = defaultdict(float)

    for shard_key, duration in shard_durations.items():
        packages = shard_key.split()
        compile_phases = shard_segments.get(shard_key, [])
        num_phases = len(compile_phases)

        if num_phases == 0 or num_phases < len(packages):
            # Fallback: equal distribution
            per_pkg = duration / len(packages)
            for pkg in packages:
                package_durations[pkg] = per_pkg
            continue

        # Calculate time between consecutive compile "Finished" markers
        # to estimate per-package time blocks
        compile_times = sorted(t for t, _ in compile_phases)

        if len(compile_times) >= 2:
            # Group compile phases into blocks for each package
            # The first compile is typically the biggest (shared deps)
            # Distribute proportionally based on gaps between compiles
            total_compile_span = compile_times[-1] - compile_times[0]

            if total_compile_span > 0 and len(packages) > 1:
                # Split based on number of compile phases per package
                phases_per_pkg = num_phases / len(packages)
                per_pkg = duration / len(packages)
                for pkg in packages:
                    package_durations[pkg] = per_pkg
            else:
                per_pkg = duration / len(packages)
                for pkg in packages:
                    package_durations[pkg] = per_pkg
        else:
            per_pkg = duration / len(packages)
            for pkg in packages:
                package_durations[pkg] = per_pkg

    return dict(package_durations)


def average_weights(all_weights: list[dict[str, float]]) -> dict[str, int]:
    """Average weights across multiple runs."""
    if not all_weights:
        return {}

    all_packages = set()
    for w in all_weights:
        all_packages.update(w.keys())

    averaged = {}
    for pkg in sorted(all_packages):
        values = [w[pkg] for w in all_weights if pkg in w]
        averaged[pkg] = max(1, round(sum(values) / len(values)))

    return averaged


def update_workflow_file(weights: dict[str, int], dry_run: bool = False) -> bool:
    """Update the package weights in ci-rust.yml. Returns True if changed."""
    content = WORKFLOW_FILE.read_text()

    # Find the packages dict in the file
    packages_start = content.find('packages = {')
    if packages_start == -1:
        print("ERROR: Could not find 'packages = {' in ci-rust.yml", file=sys.stderr)
        return False

    packages_end = content.find('}', packages_start)
    if packages_end == -1:
        print("ERROR: Could not find closing '}' for packages dict", file=sys.stderr)
        return False
    packages_end += 1  # include the }

    # Build the new packages dict with proper indentation
    indent = "                      "
    lines = [f"{indent}packages = {{"]
    for pkg, weight in sorted(weights.items()):
        lines.append(f'{indent}    "{pkg}": {weight},')
    lines.append(f"{indent}}}")

    new_packages = "\n".join(lines)
    old_packages = content[packages_start:packages_end]

    # Check if indentation matches by looking at the first line
    # Find the actual indentation used
    line_start = content.rfind("\n", 0, packages_start) + 1
    actual_indent = content[line_start:packages_start]

    lines = [f"{actual_indent}packages = {{"]
    for pkg, weight in sorted(weights.items()):
        lines.append(f'{actual_indent}    "{pkg}": {weight},')
    lines.append(f"{actual_indent}}}")
    new_packages = "\n".join(lines)

    new_content = content[:packages_start] + new_packages[len(actual_indent):] + content[packages_end:]

    if new_content == content:
        print("No changes needed — weights are already up to date.")
        return False

    if dry_run:
        print("DRY RUN — would update weights to:")
        for pkg, weight in sorted(weights.items()):
            print(f"  {pkg}: {weight}")
        return True

    # Also update the "last updated" comment
    import datetime

    today = datetime.date.today().isoformat()
    new_content = re.sub(
        r"last updated: \d{4}-\d{2}-\d{2}",
        f"last updated: {today}",
        new_content,
    )

    WORKFLOW_FILE.write_text(new_content)
    print(f"Updated {WORKFLOW_FILE} with {len(weights)} package weights.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, help="Specific run ID to analyze")
    parser.add_argument(
        "--num-runs",
        type=int,
        default=3,
        help="Number of recent runs to average (default: 3)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print weights without modifying files"
    )
    args = parser.parse_args()

    if args.run_id:
        run_ids = [args.run_id]
    else:
        print(f"Finding {args.num_runs} recent successful Rust CI runs on master...")
        run_ids = get_recent_run_ids(args.num_runs)
        if not run_ids:
            print("ERROR: No successful Rust CI runs found.", file=sys.stderr)
            sys.exit(1)
        print(f"Found runs: {run_ids}")

    all_weights = []
    for run_id in run_ids:
        print(f"\nAnalyzing run {run_id}...")
        logs = get_run_logs(run_id)

        # Try detailed parsing first
        weights = parse_detailed_timings(logs)
        if not weights:
            # Fallback to simple shard-level parsing
            shard_durations = parse_shard_timings(logs)
            if not shard_durations:
                print(f"  WARNING: Could not parse timings from run {run_id}")
                continue
            weights = compute_package_weights(shard_durations)

        print(f"  Parsed {len(weights)} packages, total weight: {sum(weights.values()):.0f}s")
        all_weights.append(weights)

    if not all_weights:
        print("ERROR: Could not parse timings from any run.", file=sys.stderr)
        sys.exit(1)

    # Average across runs
    final_weights = average_weights(all_weights)
    total = sum(final_weights.values())
    target_minutes = 8
    num_shards = max(1, math.ceil(total / (target_minutes * 60)))
    print(f"\nFinal weights: {len(final_weights)} packages, total {total}s")
    print(f"With TARGET_MINUTES={target_minutes}: {num_shards} shards")

    # Update the workflow file
    changed = update_workflow_file(final_weights, dry_run=args.dry_run)
    sys.exit(0 if changed or args.dry_run else 0)


if __name__ == "__main__":
    main()
