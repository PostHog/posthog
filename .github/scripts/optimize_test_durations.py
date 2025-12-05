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
    """Iteratively optimize synthetic durations for balanced shards."""
    sorted_tests = sorted(real_durations.keys())
    target_per_shard = sum(real_durations.values()) / num_shards

    # Initialize: use real durations, but neutralize inflated values
    # Tests above ceiling (e.g. 60s) are likely first-test-in-shard getting blamed for
    # global setup time (~240s for Django DB). Their actual test time is negligible,
    # so set them to a small value rather than avg (which would give them too much weight).
    synthetic = {}
    for test in sorted_tests:
        real = real_durations[test]
        if real > ceiling:
            synthetic[test] = 0.1  # Negligible - setup time isn't their fault
        else:
            synthetic[test] = max(0.01, real)

    best_std = float("inf")
    best_synthetic = None

    for _iteration in range(iterations):
        shards, test_to_shard = simulate_distribution(synthetic, num_shards)
        real_times, std = calculate_stats(shards, real_durations)

        if std < best_std:
            best_std = std
            best_synthetic = dict(synthetic)

        # Calculate correction for each shard
        shard_corrections = []
        for i, shard in enumerate(shards):
            if not shard:
                shard_corrections.append(1.0)
                continue
            real_time = real_times[i]
            if target_per_shard > 0:
                ratio = real_time / target_per_shard
                correction = 1.0 + (ratio - 1.0) * learning_rate
                correction = max(0.5, min(2.0, correction))
                shard_corrections.append(correction)
            else:
                shard_corrections.append(1.0)

        # Apply corrections
        for test in sorted_tests:
            shard_idx = test_to_shard.get(test, 0)
            if shard_idx < len(shard_corrections):
                synthetic[test] *= shard_corrections[shard_idx]
                synthetic[test] = max(0.001, synthetic[test])

    return best_synthetic or synthetic


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

    args = parser.parse_args()

    logger.info("Loading timing artifacts from %s...", args.artifacts_dir)
    if args.segment:
        logger.info("  Filtering to segment: %s", args.segment)
    real_durations = load_timing_artifacts(args.artifacts_dir, segment=args.segment)
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
