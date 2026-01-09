#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest>=7.0.0",
#     "pytest-split>=0.8.0",
# ]
# ///
"""
Prepare test durations for pytest-split sharding.

Merges timing artifacts from CI shards and applies a ceiling cap to inflated
first-test durations (caused by Django DB setup warm-up).

Note: pytest-split's duration_based_chunks algorithm has inherent limitations -
fast tests clustered alphabetically at the end can cause the last shard to be
much faster than others. This script doesn't try to "game" the algorithm;
it just provides clean timing data.
"""

import json
import logging
import argparse
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CEILING = 60.0


def load_timing_artifacts(artifacts_dir: Path, segment: str | None = None) -> dict[str, float]:
    """Load and merge timing data from shard artifacts.

    Args:
        artifacts_dir: Directory containing timing artifacts
        segment: If provided, only load artifacts from this segment (e.g., "Core")
                 Artifact dirs are named like "timing_data-Core-1", "timing_data-Temporal-5"
    """
    durations = {}
    for timing_file in artifacts_dir.rglob(".test_durations"):
        # Filter by segment if specified
        if segment:
            # Parent dir name is like "timing_data-Core-1"
            parent_name = timing_file.parent.name
            if not parent_name.startswith(f"timing_data-{segment}-"):
                continue
        with open(timing_file) as f:
            durations.update(json.load(f))
    return durations


def apply_ceiling_cap(durations: dict[str, float], ceiling: float = DEFAULT_CEILING) -> dict[str, float]:
    """Apply ceiling cap to inflated durations.

    First test in each shard has Django DB setup baked into its timing (~60-240s).
    Cap these to avoid skewing the timing file.
    """
    result = {}
    for test, duration in durations.items():
        if duration > ceiling:
            result[test] = ceiling
        else:
            result[test] = max(0.01, duration)
    return result


def collect_existing_tests(segment: str | None = None) -> set[str]:
    """Collect test names that actually exist in the codebase.

    This filters out stale tests from artifacts that no longer exist.
    """
    import subprocess

    # Build pytest command based on segment
    cmd = [
        "pytest",
        "posthog",
        "products",
        "ee/",
        "-m",
        "not async_migrations",
        "--ignore=posthog/temporal",
        "--ignore=posthog/dags",
        "--ignore=products/**/dags",
        "--ignore=products/batch_exports/backend/tests/temporal",
        "--ignore=common/hogvm/python/test",
        "--collect-only",
        "-q",
    ]

    # Add segment-specific filters
    if segment == "Temporal":
        cmd = [
            "pytest",
            "posthog/temporal",
            "products/batch_exports/backend/tests/temporal",
            "-m",
            "not async_migrations",
            "--collect-only",
            "-q",
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    tests = set()
    for line in result.stdout.splitlines():
        if "::" in line:
            tests.add(line.strip())
    return tests


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Prepare test durations for pytest-split sharding")
    parser.add_argument("artifacts_dir", type=Path, help="Directory containing timing artifacts")
    parser.add_argument("output_file", type=Path, help="Output file for processed durations")
    parser.add_argument(
        "--ceiling",
        type=float,
        default=DEFAULT_CEILING,
        help=f"Duration ceiling for inflated tests (default: {DEFAULT_CEILING}s)",
    )
    parser.add_argument(
        "--segment",
        type=str,
        default=None,
        help="Only load artifacts from this segment (e.g., 'Core'). Filters by artifact dir name.",
    )
    parser.add_argument(
        "--filter-existing",
        action="store_true",
        help="Filter to only tests that exist in the codebase (runs pytest --collect-only)",
    )

    args = parser.parse_args()

    logger.info("Loading timing artifacts from %s...", args.artifacts_dir)
    if args.segment:
        logger.info("  Filtering to segment: %s", args.segment)
    real_durations = load_timing_artifacts(args.artifacts_dir, segment=args.segment)
    logger.info("  Loaded %d tests from artifacts", len(real_durations))

    # Filter to only existing tests if requested
    if args.filter_existing:
        logger.info("Collecting existing tests from codebase...")
        existing_tests = collect_existing_tests(segment=args.segment)
        logger.info("  Found %d tests in codebase", len(existing_tests))

        before_count = len(real_durations)
        real_durations = {k: v for k, v in real_durations.items() if k in existing_tests}
        logger.info(
            "  Filtered to %d tests (removed %d stale)", len(real_durations), before_count - len(real_durations)
        )
    logger.info("  Total tests: %d", len(real_durations))

    logger.info("Applying ceiling cap (%.0fs)...", args.ceiling)
    processed = apply_ceiling_cap(real_durations, ceiling=args.ceiling)

    # Save
    with open(args.output_file, "w") as f:
        json.dump(processed, f, separators=(",", ":"), sort_keys=True)
    logger.info("Saved %d tests to %s", len(processed), args.output_file)


if __name__ == "__main__":
    main()
