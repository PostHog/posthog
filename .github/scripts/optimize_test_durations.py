#!/usr/bin/env python3
"""
Optimize test durations for balanced pytest-split sharding.

The duration_based_chunks algorithm fills shards sequentially until hitting
a target duration. This can cause empty shards when:
- Some shards overshoot the target (eating into budget for later shards)
- Last shards don't have enough tests left

This script uses iterative feedback optimization:
1. Start with real durations from CI artifacts
2. Simulate which shard each test lands in
3. For slow shards (real time > target): inflate durations → fills faster → pushes tests out
4. For fast shards (real time < target): deflate durations → more tests fit
5. Repeat until convergence

Result: synthetic durations that produce balanced real execution times.
"""

import json
import logging
import argparse
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_NUM_SHARDS = 40
DEFAULT_CEILING = 60.0
DEFAULT_LEARNING_RATE = 0.3
DEFAULT_ITERATIONS = 50


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


def simulate_distribution(test_durations: dict[str, float], num_shards: int) -> tuple[list[list[str]], dict[str, int]]:
    """Simulate pytest-split's duration_based_chunks algorithm."""
    sorted_tests = sorted(test_durations.keys())
    total_duration = sum(test_durations.values())
    target_per_shard = total_duration / num_shards

    shards: list[list[str]] = []
    current_shard: list[str] = []
    current_duration = 0.0
    test_to_shard: dict[str, int] = {}

    for test in sorted_tests:
        shard_idx = len(shards)
        current_shard.append(test)
        test_to_shard[test] = shard_idx
        current_duration += test_durations[test]

        if current_duration >= target_per_shard and len(shards) < num_shards - 1:
            shards.append(current_shard)
            current_shard = []
            current_duration = 0

    if current_shard:
        shards.append(current_shard)

    while len(shards) < num_shards:
        shards.append([])

    return shards, test_to_shard


def calculate_stats(shards: list[list[str]], real_durations: dict[str, float]) -> tuple[list[float], float]:
    """Calculate real execution times and standard deviation."""
    real_times = [sum(real_durations.get(t, 0) for t in shard) for shard in shards]
    avg = sum(real_times) / len(real_times)
    std = (sum((t - avg) ** 2 for t in real_times) / len(real_times)) ** 0.5
    return real_times, std


def optimize(
    real_durations: dict[str, float],
    num_shards: int = DEFAULT_NUM_SHARDS,
    ceiling: float = DEFAULT_CEILING,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    iterations: int = DEFAULT_ITERATIONS,
) -> dict[str, float]:
    """Simple ceiling-cap optimization.

    Just cap inflated first-test durations and use real durations otherwise.
    This is simple and predictable.
    """
    sorted_tests = sorted(real_durations.keys())

    # Cap inflated durations (first-test-in-shard warm-up artifacts)
    # and ensure minimum duration for tests with 0 or very small times
    capped = {}
    for test in sorted_tests:
        real = real_durations[test]
        if real > ceiling:
            # Likely first-test warm-up, cap it
            capped[test] = ceiling
        else:
            capped[test] = max(0.01, real)

    return capped


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

    parser = argparse.ArgumentParser(description="Optimize test durations for balanced pytest-split sharding")
    parser.add_argument("artifacts_dir", type=Path, help="Directory containing timing artifacts")
    parser.add_argument("output_file", type=Path, help="Output file for optimized durations")
    parser.add_argument(
        "--num-shards", type=int, default=DEFAULT_NUM_SHARDS, help=f"Number of shards (default: {DEFAULT_NUM_SHARDS})"
    )
    parser.add_argument(
        "--ceiling",
        type=float,
        default=DEFAULT_CEILING,
        help=f"Duration ceiling for inflated tests (default: {DEFAULT_CEILING}s)",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=DEFAULT_LEARNING_RATE,
        help=f"Learning rate for optimization (default: {DEFAULT_LEARNING_RATE})",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Number of optimization iterations (default: {DEFAULT_ITERATIONS})",
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

    target = sum(real_durations.values()) / args.num_shards
    logger.info("  Target real time per shard: %.0fs", target)

    logger.info(
        "Optimizing durations (shards=%d, ceiling=%.0fs, lr=%.2f, iterations=%d)...",
        args.num_shards,
        args.ceiling,
        args.learning_rate,
        args.iterations,
    )
    optimized = optimize(
        real_durations,
        num_shards=args.num_shards,
        ceiling=args.ceiling,
        learning_rate=args.learning_rate,
        iterations=args.iterations,
    )

    # Analyze result
    shards, _ = simulate_distribution(optimized, args.num_shards)
    real_times, std = calculate_stats(shards, real_durations)
    empty = sum(1 for s in shards if not s)

    logger.info("Results:")
    logger.info("  Real time range: %.0fs - %.0fs", min(real_times), max(real_times))
    logger.info("  Std dev: %.0fs", std)
    logger.info("  Empty shards: %d", empty)

    # Save
    with open(args.output_file, "w") as f:
        json.dump(optimized, f, separators=(",", ":"), sort_keys=True)
    logger.info("Saved to %s", args.output_file)


if __name__ == "__main__":
    main()
