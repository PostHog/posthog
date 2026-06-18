#!/usr/bin/env python3
# ruff: noqa: T201 stdout is this script's output contract
"""Compute per-shard pytest targets for the Django CI matrix.

Every Django shard historically ran `pytest posthog ee/ --splits N --group G`,
which makes pytest-split collect (import) the *entire* test tree before
deselecting the tests outside the shard's group. That full-tree import is the
dominant cost of the pre-first-test "setup" span and is paid by every shard.

This script replaces that with file-level sharding: it assigns whole test
files to shards (balanced by recorded duration) so each shard only collects
its own files. Files larger than one shard's budget are split across dedicated
shards with pytest-split, so balance is preserved for the few heavy files.

Coverage is sourced from the filesystem (the authoritative set of files pytest
would collect), so newly added / untimed files are always assigned. Durations
are used only as weights for balancing.

Output (stdout): a single line of pytest arguments for the requested group,
e.g.
    posthog/api/test/test_a.py ee/foo/test_b.py
or for a heavy file split across shards:
    posthog/hogql/database/schema/test/test_system_tables.py --splits 2 --group 1

Fallback: if .test_durations is missing/unusable or the universe is empty, the
script prints the legacy whole-tree invocation for the segment, so behaviour is
identical to before file-level sharding.
"""

from __future__ import annotations

import os
import sys
import json
import math
import argparse
import statistics
from dataclasses import dataclass, field

# Mirrors DJANGO_SEGMENTS in .github/scripts/turbo-discover.js and the pytest
# invocations in .github/workflows/ci-backend.yml. Keep all three in sync.
#   include: path prefixes (dirs end with "/") or explicit files
#   exclude: path prefixes removed from the include set
#   legacy:  positional args used for the whole-tree fallback (must match the
#            historical ci-backend.yml invocation for the segment)
SEGMENTS: dict[str, dict] = {
    "Core": {
        "include": ["posthog/", "ee/"],
        "exclude": ["posthog/temporal/", "posthog/dags/", "common/hogvm/"],
        "legacy": ["posthog", "ee/"],
    },
    "CorePOE": {
        "include": [
            "posthog/clickhouse/",
            "posthog/queries/",
            "products/product_analytics/backend/api/test/",
            "posthog/api/test/dashboards/test_dashboard.py",
            "ee/clickhouse/",
        ],
        "exclude": ["posthog/hogql_queries/", "posthog/hogql/"],
        "legacy": [
            "./posthog/clickhouse/",
            "./posthog/queries/",
            "./products/product_analytics/backend/api/test/",
            "./posthog/api/test/dashboards/test_dashboard.py",
            "ee/clickhouse/",
        ],
    },
    "Temporal": {
        "include": [
            "posthog/temporal/",
            "products/batch_exports/backend/tests/temporal/",
            "products/tasks/backend/temporal/",
        ],
        "exclude": [],
        "legacy": [
            "posthog/temporal",
            "products/batch_exports/backend/tests/temporal",
            "products/tasks/backend/temporal",
        ],
    },
}

# pytest.ini `addopts` --ignore paths, plus dirs Django invocations ignore.
# Globally excluded so the filesystem universe matches what pytest collects.
GLOBAL_IGNORE_PREFIXES = [
    "posthog/user_scripts/",
    "services/llm-gateway/",
    "services/stripe-mock/",
    "common/ingestion/acceptance_tests/",
    "tools/hogli/",
    "tools/hogli-commands/",
    "tools/traffic-sim/",
    "tools/query-performance-ai/",
]

# pytest default `python_files` patterns.
TEST_FILE_SUFFIX = "_test.py"
TEST_FILE_PREFIX = "test_"


@dataclass
class ShardSpec:
    """One shard's work: a set of whole files, or a slice of one big file."""

    files: list[str] = field(default_factory=list)
    weight: float = 0.0
    # When set, this shard runs a single big file under pytest-split.
    split_total: int | None = None
    split_group: int | None = None

    def pytest_args(self) -> str:
        if self.split_total is not None:
            return f"{self.files[0]} --splits {self.split_total} --group {self.split_group}"
        return " ".join(self.files)


def is_test_file(name: str) -> bool:
    return name.endswith(".py") and (name.startswith(TEST_FILE_PREFIX) or name.endswith(TEST_FILE_SUFFIX))


def _excluded(path: str, exclude: list[str]) -> bool:
    return any(path.startswith(p) for p in exclude) or any(path.startswith(p) for p in GLOBAL_IGNORE_PREFIXES)


def discover_files(segment: str, repo_root: str) -> list[str]:
    """All test files pytest would collect for the segment, as repo-relative posix paths."""
    cfg = SEGMENTS[segment]
    exclude = cfg["exclude"]
    found: set[str] = set()
    for inc in cfg["include"]:
        abs_inc = os.path.join(repo_root, inc)
        if inc.endswith(".py"):
            if os.path.isfile(abs_inc) and not _excluded(inc, exclude):
                found.add(inc)
            continue
        for dirpath, dirnames, filenames in os.walk(abs_inc):
            rel_dir = os.path.relpath(dirpath, repo_root).replace(os.sep, "/")
            # Prune excluded subtrees early so we don't descend into them.
            if _excluded(rel_dir + "/", exclude):
                dirnames[:] = []
                continue
            for fn in filenames:
                if not is_test_file(fn):
                    continue
                rel = f"{rel_dir}/{fn}" if rel_dir != "." else fn
                if not _excluded(rel, exclude):
                    found.add(rel)
    return sorted(found)


def load_file_weights(durations_path: str) -> dict[str, float]:
    """Per-file summed durations from .test_durations (keys are `path::nodeid`)."""
    try:
        with open(durations_path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    weights: dict[str, float] = {}
    for nodeid, dur in data.items():
        if not isinstance(dur, int | float) or not math.isfinite(dur) or dur < 0:
            continue
        path = nodeid.split("::", 1)[0]
        weights[path] = weights.get(path, 0.0) + float(dur)
    return weights


def weighted_files(files: list[str], weights: dict[str, float]) -> list[tuple[str, float]]:
    """Attach a weight to every file; untimed files get the median timed weight."""
    timed = [weights[f] for f in files if f in weights and weights[f] > 0]
    default = statistics.median(timed) if timed else 1.0
    return [(f, weights.get(f, 0.0) or default) for f in files]


def build_plan(files_with_weights: list[tuple[str, float]], shards: int) -> list[ShardSpec]:
    """Hybrid bin-packing: oversized files get dedicated split-shards; the rest
    are LPT-packed into whole-file shards. Returns exactly `shards` specs (so a
    given group always maps to a spec) and partitions every file across them.
    Deterministic for a fixed input."""
    total = sum(w for _, w in files_with_weights)
    ideal = total / shards if shards else total

    # Split a file across dedicated shards only when it's heavier than one
    # shard's budget. Allocate splits heaviest-first, but never consume so many
    # shards that fewer than one remains for the (always non-empty) whole-file
    # pool — that cap keeps the plan length exactly `shards` and is only ever
    # hit in degenerate inputs (shards approaching the file count); in CI files
    # vastly outnumber shards so all oversized files get their splits.
    oversized = sorted(
        [(f, w) for f, w in files_with_weights if ideal > 0 and w > ideal],
        key=lambda x: (-x[1], x[0]),
    )
    split_specs: list[ShardSpec] = []
    whole: list[tuple[str, float]] = []
    for f, w in oversized:
        pieces = max(2, math.ceil(w / ideal))
        if len(split_specs) + pieces <= shards - 1:
            for g in range(1, pieces + 1):
                split_specs.append(ShardSpec(files=[f], weight=w / pieces, split_total=pieces, split_group=g))
        else:
            whole.append((f, w))  # no split budget left — pack whole, accept its weight

    whole += [(f, w) for f, w in files_with_weights if not (ideal > 0 and w > ideal)]
    whole.sort(key=lambda x: (-x[1], x[0]))

    whole_bins = shards - len(split_specs)
    bins = [ShardSpec() for _ in range(whole_bins)]
    for f, w in whole:
        target = min(bins, key=lambda b: (b.weight, len(b.files)))
        target.files.append(f)
        target.weight += w

    # Canonical order: whole-file shards first, then split-shards. Stable so a
    # given (shards, group) maps to the same spec on every runner.
    return bins + split_specs


def legacy_args(segment: str, shards: int, group: int) -> str:
    cfg = SEGMENTS[segment]
    parts = list(cfg["legacy"])
    for p in cfg["exclude"]:
        # ee/clickhouse style excludes aren't expressible as --ignore here; the
        # legacy CorePOE/Core invocations used explicit --ignore for these.
        parts.append(f"--ignore={p.rstrip('/')}")
    parts.append(f"--splits {shards} --group {group}")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--segment", required=True, choices=sorted(SEGMENTS))
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--group", type=int, help="1-based shard group to print args for")
    parser.add_argument("--repo-root", default=os.getcwd())
    parser.add_argument("--durations", default=os.path.join(os.getcwd(), ".test_durations"))
    parser.add_argument("--check", action="store_true", help="validate coverage + print balance stats to stderr")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.shards < 1:
        print(f"::error::invalid --shards {args.shards}", file=sys.stderr)
        return 2

    files = discover_files(args.segment, args.repo_root)
    weights = load_file_weights(args.durations)

    # Fallback to the whole-tree invocation when we can't shard meaningfully.
    if not files or not weights or args.shards < 2:
        if args.group is not None:
            print(legacy_args(args.segment, args.shards, args.group))
        print(
            f"shard_django_files: fallback to legacy invocation "
            f"(files={len(files)}, timed={len(weights)}, shards={args.shards})",
            file=sys.stderr,
        )
        return 0

    plan = build_plan(weighted_files(files, weights), args.shards)

    if args.check:
        assigned = [f for spec in plan for f in spec.files]
        whole = [f for spec in plan if spec.split_total is None for f in spec.files]
        # Whole-file assignments must be a partition of the non-split universe.
        split_files = {spec.files[0] for spec in plan if spec.split_total is not None}
        expected_whole = sorted(set(files) - split_files)
        dupes = sorted({f for f in whole if whole.count(f) > 1})
        missing = sorted(set(files) - set(assigned))
        weights_per = [s.weight for s in plan]
        ideal = sum(w for _, w in weighted_files(files, weights)) / args.shards
        print(
            f"segment={args.segment} shards={args.shards} files={len(files)} "
            f"split_files={len(split_files)} plan_len={len(plan)}",
            file=sys.stderr,
        )
        print(
            f"coverage: missing={len(missing)} dupes={len(dupes)} "
            f"whole_partition_ok={sorted(set(whole)) == expected_whole}",
            file=sys.stderr,
        )
        print(
            f"balance: ideal={ideal:.0f}s max={max(weights_per):.0f}s "
            f"min={min(weights_per):.0f}s imbalance=+{(max(weights_per) - ideal) / ideal * 100:.1f}%",
            file=sys.stderr,
        )
        if missing or dupes or len(plan) != args.shards:
            print("::error::shard plan invalid", file=sys.stderr)
            return 1

    if args.group is not None:
        if not 1 <= args.group <= len(plan):
            print(f"::error::group {args.group} out of range 1..{len(plan)}", file=sys.stderr)
            return 2
        print(plan[args.group - 1].pytest_args())

    return 0


if __name__ == "__main__":
    sys.exit(main())
