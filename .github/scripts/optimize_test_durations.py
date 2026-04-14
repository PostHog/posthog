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

Merges timing artifacts from CI shards and corrects migration-inflated
first-test durations using JUnit results to identify carriers.

Each shard's first test absorbs Django migration overhead (~6.5 min),
making that test look artificially slow. This script detects those
carriers, subtracts the migration tax, and outputs clean durations
for balanced pytest-split distribution.
"""

import glob
import json
import logging
import argparse
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_DURATION = 0.01
# Tests with recorded duration above this threshold in a single shard
# are candidates for migration carriers (real tests rarely exceed this)
CARRIER_THRESHOLD_SECONDS = 200.0


@dataclass
class ShardTimings:
    """Timing data from a single CI shard's .test_durations artifact."""

    name: str
    durations: dict[str, float]

    @classmethod
    def load_all(cls, artifacts_dir: Path, segment: str | None = None) -> list["ShardTimings"]:
        """Load per-shard timing artifacts, optionally filtered by segment.

        Artifact dirs are named like "timing_data-Core-1", "timing_data-Temporal-5".
        """
        shards = []
        for timing_file in sorted(artifacts_dir.rglob(".test_durations")):
            parent_name = timing_file.parent.name
            if segment and not parent_name.startswith(f"timing_data-{segment}-"):
                continue
            with open(timing_file) as f:
                shards.append(cls(name=parent_name, durations=json.load(f)))
        return shards


@dataclass
class JUnitShard:
    """JUnit results from a single CI shard."""

    name: str
    first_test_id: str
    first_test_duration: float

    @classmethod
    def load_all(cls, junit_dir: Path, segment: str | None = None) -> list["JUnitShard"]:
        """Load JUnit XMLs and extract the first test (carrier) from each shard.

        JUnit artifact dirs are named like "junit-results-backend-core-1".
        """
        shards = []
        for shard_dir in sorted(junit_dir.iterdir()):
            if not shard_dir.is_dir():
                continue

            # Filter by segment if specified
            if segment:
                seg_lower = segment.lower()
                dir_lower = shard_dir.name.lower()
                # Match "junit-results-backend-core-1" for segment "Core"
                # but not "core-poe-1" when looking for "Core"
                if seg_lower == "core":
                    if "core" not in dir_lower or "core-poe" in dir_lower:
                        continue
                elif f"-{seg_lower}" not in dir_lower:
                    continue

            xml_files = list(shard_dir.glob("*.xml"))
            if not xml_files:
                continue

            first = cls._find_first_test(xml_files[0])
            if first:
                shards.append(cls(name=shard_dir.name, **first))

        return shards

    @staticmethod
    def _find_first_test(xml_path: Path) -> dict | None:
        """Extract the first testcase from a JUnit XML file."""
        tree = ET.parse(xml_path)
        for tc in tree.getroot().iter("testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            duration = float(tc.get("time", 0))
            pytest_id = _junit_to_pytest_id(classname, name)
            if pytest_id:
                return {"first_test_id": pytest_id, "first_test_duration": duration}
        return None


@dataclass
class MigrationTaxResult:
    """Result of migration tax detection and correction."""

    corrected_durations: dict[str, float]
    migration_tax_seconds: float
    carriers_found: int


class TimingMerger:
    """Merges per-shard timing artifacts using outlier detection.

    Each shard writes the full test map via --store-durations, but only
    updates durations for tests it actually ran. Non-run tests retain
    stale values from the previous .test_durations. A naive merge
    (last-write-wins) can overwrite real values with stale ones.

    This merger collects all values per test across shards and picks
    the outlier (the value from the shard that actually ran the test).
    """

    def __init__(self, shards: list[ShardTimings]):
        self.shards = shards

    def merge(self) -> dict[str, float]:
        if not self.shards:
            return {}

        if len(self.shards) == 1:
            return dict(self.shards[0].durations)

        test_keys: set[str] = set()
        for shard in self.shards:
            test_keys.update(shard.durations.keys())

        merged = {}
        for test in test_keys:
            values = [shard.durations.get(test, 0) for shard in self.shards]
            merged[test] = self._pick_real_value(values)

        return merged

    @staticmethod
    def _pick_real_value(values: list[float]) -> float:
        """Pick the real duration from a list of per-shard values.

        Most values are stale (identical across shards). The outlier—the
        value that differs from the majority—is the real measurement from
        the shard that ran this test.
        """
        unique = set(values)
        if len(unique) == 1:
            return values[0]

        counter = Counter(values)
        most_common_val = counter.most_common(1)[0][0]
        outliers = [v for v in values if v != most_common_val]
        return outliers[0] if outliers else most_common_val


class MigrationTaxCorrector:
    """Detects and corrects migration-inflated first-test durations.

    The first test in each CI shard absorbs Django migration overhead
    (creating template DB, running migrations, etc.). This inflates that
    test's recorded duration by ~6.5 min, which skews pytest-split's
    shard balancing.

    Two detection modes:
    - JUnit-based (preferred): uses JUnit XML to identify the first test
      per shard — precise, no false positives.
    - Statistical fallback: when JUnit is unavailable, identifies tests
      whose duration is a clear outlier (>CARRIER_THRESHOLD_SECONDS above
      the next-highest test in the merged data). Expects exactly one
      carrier per shard, using the shard count as a guide.
    """

    def __init__(
        self,
        durations: dict[str, float],
        junit_shards: list[JUnitShard] | None = None,
        expected_shard_count: int = 0,
    ):
        self.durations = durations
        self.junit_shards = junit_shards or []
        self.expected_shard_count = expected_shard_count

    def correct(self) -> MigrationTaxResult:
        if self.junit_shards:
            carriers = self._find_carriers_from_junit()
        elif self.expected_shard_count > 0:
            carriers = self._find_carriers_statistically()
        else:
            logger.info("  No JUnit data or shard count — skipping carrier correction")
            return MigrationTaxResult(
                corrected_durations=dict(self.durations),
                migration_tax_seconds=0,
                carriers_found=0,
            )

        if not carriers:
            logger.info("  No migration carriers found")
            return MigrationTaxResult(
                corrected_durations=dict(self.durations),
                migration_tax_seconds=0,
                carriers_found=0,
            )

        migration_tax = self._estimate_tax(carriers)
        corrected = self._apply_correction(carriers, migration_tax)

        return MigrationTaxResult(
            corrected_durations=corrected,
            migration_tax_seconds=migration_tax,
            carriers_found=len(carriers),
        )

    def _find_carriers_from_junit(self) -> dict[str, float]:
        """Identify carriers from JUnit first-test-per-shard data."""
        carriers = {}
        for junit_shard in self.junit_shards:
            test_id = junit_shard.first_test_id
            duration = junit_shard.first_test_duration

            if duration < CARRIER_THRESHOLD_SECONDS:
                continue

            matched_key = self._match_duration_key(test_id)
            if matched_key:
                carriers[matched_key] = duration
                logger.debug("  Carrier (JUnit): %s (%.0fs) from %s", matched_key[:60], duration, junit_shard.name)
            else:
                logger.warning("  Could not match carrier %s to durations", test_id[:60])

        return carriers

    def _find_carriers_statistically(self) -> dict[str, float]:
        """Identify carriers by finding the N highest-duration outliers.

        Uses expected_shard_count as the number of carriers to look for.
        Only selects tests above CARRIER_THRESHOLD_SECONDS to avoid
        false positives from genuinely slow tests.
        """
        candidates = sorted(self.durations.items(), key=lambda x: -x[1])

        # Take the top N candidates that are above threshold
        carriers = {}
        for test_id, duration in candidates:
            if duration < CARRIER_THRESHOLD_SECONDS:
                break
            carriers[test_id] = duration
            if len(carriers) >= self.expected_shard_count:
                break

        if carriers:
            # Sanity check: carriers should be clustered together (all ~same duration)
            carrier_durs = list(carriers.values())
            spread = max(carrier_durs) - min(carrier_durs)
            if spread > 120:
                logger.warning("  Carrier duration spread is %.0fs — may include genuinely slow tests", spread)

            logger.info(
                "  Found %d statistical carriers (expected %d shards)",
                len(carriers),
                self.expected_shard_count,
            )

        return carriers

    def _match_duration_key(self, junit_test_id: str) -> str | None:
        """Find the matching key in durations for a JUnit test ID."""
        if junit_test_id in self.durations:
            return junit_test_id

        # Fuzzy match: extract test name and class, search durations
        parts = junit_test_id.split("::")
        if len(parts) >= 2:
            test_name = parts[-1]
            class_name = parts[-2] if len(parts) >= 3 else ""
            for key in self.durations:
                if test_name in key and (not class_name or class_name in key):
                    return key

        return None

    @staticmethod
    def _estimate_tax(carriers: dict[str, float]) -> float:
        """Estimate migration tax as the average carrier duration.

        The carrier's recorded duration ≈ real_duration + migration_tax.
        Since real_duration is typically small (<15s), the carrier duration
        is a good approximation of the tax itself.
        """
        durations = list(carriers.values())
        tax = sum(durations) / len(durations)
        logger.info("  Migration tax estimate: %.0fs (%.1fm) from %d carriers", tax, tax / 60, len(carriers))
        return tax

    def _apply_correction(self, carriers: dict[str, float], migration_tax: float) -> dict[str, float]:
        """Subtract migration tax from carrier durations."""
        corrected = dict(self.durations)
        for test_id, carrier_dur in carriers.items():
            original = corrected.get(test_id, carrier_dur)
            adjusted = max(MIN_DURATION, original - migration_tax)
            corrected[test_id] = adjusted
            logger.info("  Corrected %s: %.0fs -> %.1fs", test_id[:60], original, adjusted)
        return corrected


def _junit_to_pytest_id(classname: str, testname: str) -> str | None:
    """Convert JUnit classname + testname to a pytest node ID.

    JUnit: classname="posthog.api.test.test_user.TestUserAPI" name="test_xyz"
    pytest: "posthog/api/test/test_user.py::TestUserAPI::test_xyz"
    """
    parts = classname.split(".")

    # Find where the module ends and class begins (first CamelCase part)
    split_idx = len(parts)
    for i, part in enumerate(parts):
        if part and part[0].isupper():
            split_idx = i
            break

    if split_idx == 0:
        return None

    module_path = "/".join(parts[:split_idx]) + ".py"
    class_parts = parts[split_idx:]
    class_path = "::".join(class_parts) if class_parts else ""

    if class_path:
        return f"{module_path}::{class_path}::{testname}"
    return f"{module_path}::{testname}"


def ensure_minimum_duration(durations: dict[str, float]) -> dict[str, float]:
    """Ensure all durations have a minimum value for pytest-split."""
    return {test: max(MIN_DURATION, dur) for test, dur in durations.items()}


def collect_existing_tests(segment: str | None = None) -> set[str]:
    """Collect test names that actually exist in the codebase.

    Filters out stale tests from artifacts that no longer exist.
    """
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
        "--junit-dir",
        type=Path,
        default=None,
        help="Directory containing JUnit XML artifacts. Enables precise migration tax correction.",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=0,
        help="Expected number of shards. Enables statistical carrier detection when JUnit is unavailable.",
    )
    parser.add_argument(
        "--filter-existing",
        action="store_true",
        help="Filter to only tests that exist in the codebase (runs pytest --collect-only)",
    )

    args = parser.parse_args()

    # Load per-shard timing data
    logger.info("Loading timing artifacts from %s...", args.artifacts_dir)
    if args.segment:
        logger.info("  Filtering to segment: %s", args.segment)
    shards = ShardTimings.load_all(args.artifacts_dir, segment=args.segment)
    logger.info("  Loaded %d shards", len(shards))

    # Merge using outlier detection (not naive last-wins)
    logger.info("Merging with outlier detection...")
    durations = TimingMerger(shards).merge()
    logger.info("  Merged %d tests", len(durations))

    # Correct migration-inflated first-test durations
    junit_shards = None
    shard_count = args.shard_count or len(shards)

    if args.junit_dir and args.junit_dir.exists():
        logger.info("Correcting migration tax using JUnit from %s...", args.junit_dir)
        junit_shards = JUnitShard.load_all(args.junit_dir, segment=args.segment)
        logger.info("  Found %d JUnit shards", len(junit_shards))
    elif args.junit_dir:
        logger.warning("JUnit dir %s not found", args.junit_dir)

    if junit_shards or shard_count > 0:
        if not junit_shards:
            logger.info("Correcting migration tax statistically (expected %d shards)...", shard_count)

        result = MigrationTaxCorrector(
            durations,
            junit_shards=junit_shards,
            expected_shard_count=shard_count,
        ).correct()
        durations = result.corrected_durations

        if result.migration_tax_seconds > 0:
            logger.info(
                "  Corrected %d carriers, migration tax: %.0fs (%.1fm)",
                result.carriers_found,
                result.migration_tax_seconds,
                result.migration_tax_seconds / 60,
            )

    # Filter to only existing tests if requested
    if args.filter_existing:
        logger.info("Collecting existing tests from codebase...")
        existing_tests = collect_existing_tests(segment=args.segment)
        logger.info("  Found %d tests in codebase", len(existing_tests))

        before_count = len(durations)
        durations = {k: v for k, v in durations.items() if k in existing_tests}
        logger.info("  Filtered to %d tests (removed %d stale)", len(durations), before_count - len(durations))

    logger.info("  Total tests: %d", len(durations))
    processed = ensure_minimum_duration(durations)

    with open(args.output_file, "w") as f:
        json.dump(processed, f, indent=4, sort_keys=True)
        f.write("\n")
    logger.info("Saved %d tests to %s", len(processed), args.output_file)


if __name__ == "__main__":
    main()
