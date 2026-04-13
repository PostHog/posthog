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

Merges timing artifacts from CI shards. First-test durations include Django
migration overhead (~6.5 min) which is preserved so pytest-split can account
for it when distributing tests across shards.
"""

import glob
import json
import logging
import argparse
from pathlib import Path

logger = logging.getLogger(__name__)


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


def ensure_minimum_duration(durations: dict[str, float]) -> dict[str, float]:
    """Ensure all durations have a minimum value for pytest-split."""
    return {test: max(0.01, dur) for test, dur in durations.items()}


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
    elif segment == "Dagster":
        # Expand glob in Python since subprocess won't do shell expansion
        product_dags = glob.glob("products/**/dags", recursive=True)
        cmd = [
            "pytest",
            "posthog/dags",
            *product_dags,
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

    processed = ensure_minimum_duration(real_durations)

    # Save
    with open(args.output_file, "w") as f:
        json.dump(processed, f, indent=4, sort_keys=True)
        f.write("\n")
    logger.info("Saved %d tests to %s", len(processed), args.output_file)


if __name__ == "__main__":
    main()
