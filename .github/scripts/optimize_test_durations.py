#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest>=7.0.0",
#     "pytest-split>=0.8.0",
#     "defusedxml>=0.7.1",
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

import re
import sys
import glob
import json
import logging
import argparse
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import defusedxml.ElementTree as ET
from defusedxml.ElementTree import ParseError

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


# Maps the script's segment names to the artifact-key fragment used by
# ci-backend.yml ("junit-results-backend-<artifact-key>-<group>"). Add new
# segments here when adding JUnit-mode carrier detection for them.
_JUNIT_ARTIFACT_KEY = {"Core": "core", "CorePOE": "core-poe", "Temporal": "temporal"}


@dataclass
class JUnitShard:
    """JUnit results from a single CI shard."""

    name: str
    first_test_id: str

    @classmethod
    def load_all(cls, junit_dir: Path, segment: str | None = None) -> list["JUnitShard"]:
        """Load JUnit XMLs and extract the first test (carrier) from each shard.

        JUnit artifact dirs are named like "junit-results-backend-core-1".
        Segment match is anchored at the artifact prefix so "Core" doesn't
        accidentally pick up "core-poe" or any future "*-core-*" name, and
        "CorePOE" matches "core-poe" instead of the absent substring "corepoe".
        """
        shards = []
        for shard_dir in sorted(junit_dir.iterdir()):
            if not shard_dir.is_dir():
                continue

            if segment:
                artifact_key = _JUNIT_ARTIFACT_KEY.get(segment, segment.lower())
                # Anchor with `\d+$` so the Core prefix doesn't accidentally
                # eat core-poe-N (which also starts with junit-results-backend-core-).
                pattern = re.compile(rf"^junit-results-backend-{re.escape(artifact_key)}-\d+$")
                if not pattern.match(shard_dir.name.lower()):
                    continue

            xml_files = sorted(shard_dir.glob("*.xml"))
            if not xml_files:
                continue

            first_test_id = cls._find_first_test(xml_files[0])
            if first_test_id:
                shards.append(cls(name=shard_dir.name, first_test_id=first_test_id))

        return shards

    @staticmethod
    def _find_first_test(xml_path: Path) -> str | None:
        """Extract the first parseable testcase id from a JUnit XML file."""
        try:
            tree = ET.parse(xml_path)
        except ParseError as e:
            logger.warning("  Could not parse JUnit XML %s: %s", xml_path, e)
            return None
        for tc in tree.getroot().iter("testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            pytest_id = _junit_to_pytest_id(classname, name)
            if pytest_id:
                return pytest_id
        return None


@dataclass
class MigrationTaxResult:
    """Result of migration tax detection and correction."""

    corrected_durations: dict[str, float]
    migration_tax_seconds: float
    carriers_found: int


def outlier_merge_durations(sources: list[dict[str, float]]) -> dict[str, float]:
    """Outlier-merge per-test durations across N input dicts.

    Each source carries the full test map with fresh values only for tests
    actually measured by that source; the rest are stale passthroughs from
    a shared input file. A naive last-write-wins merge overwrites real
    values with stale ones — instead pick the per-test value that differs
    from the majority across sources. Falls back to first value if all
    sources agree.

    Single source of truth for outlier merging — used both by per-segment
    artifact processing (TimingMerger over ShardTimings) and by the
    cross-segment merge step in the timing update workflow.
    """
    if not sources:
        return {}
    if len(sources) == 1:
        return dict(sources[0])

    test_keys: set[str] = set()
    for source in sources:
        test_keys.update(source.keys())

    merged: dict[str, float] = {}
    for test in test_keys:
        values = [source[test] for source in sources if test in source]
        if not values:
            continue
        merged[test] = _pick_outlier(values)
    return merged


def _pick_outlier(values: list[float]) -> float:
    if len(set(values)) == 1:
        return values[0]
    counter = Counter(values)
    most_common_val = counter.most_common(1)[0][0]
    outliers = [v for v in values if v != most_common_val]
    return outliers[0] if outliers else most_common_val


class TimingMerger:
    """Merges per-shard timing artifacts using outlier detection.

    Thin wrapper around outlier_merge_durations() that adapts the
    ShardTimings interface used by per-segment processing.
    """

    def __init__(self, shards: list[ShardTimings]):
        self.shards = shards

    def merge(self) -> dict[str, float]:
        return outlier_merge_durations([shard.durations for shard in self.shards])


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
        """Identify carriers from JUnit first-test-per-shard data.

        JUnit XMLs are produced with `-o junit_duration_report=call`, so the
        `time` attribute reflects only call time, not Django setup/migration.
        Use JUnit only to identify the first test per shard, then check the
        merged .test_durations value for that test to decide if it's actually
        a carrier (carriers absorb setup time into their recorded duration).
        """
        carriers = {}
        for junit_shard in self.junit_shards:
            test_id = junit_shard.first_test_id

            matched_key = self._match_duration_key(test_id)
            if not matched_key:
                logger.warning("  Could not match first test %s to durations", test_id[:60])
                continue

            recorded_duration = self.durations.get(matched_key, 0.0)
            if recorded_duration < CARRIER_THRESHOLD_SECONDS:
                continue

            carriers[matched_key] = recorded_duration
            logger.debug(
                "  Carrier (JUnit): %s recorded=%.0fs from %s",
                matched_key[:60],
                recorded_duration,
                junit_shard.name,
            )

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
        """Find the matching key in durations for a JUnit test ID.

        Prefers exact match. Falls back to suffix match on the `::class::test`
        tail — anchored, so a JUnit id of `test_create` cannot pick up
        `test_create_user`. JUnit IDs and pytest node IDs sometimes differ
        only in file-path prefix (e.g. relative vs absolute), so suffix is
        the right comparison.
        """
        if junit_test_id in self.durations:
            return junit_test_id

        parts = junit_test_id.split("::")
        if len(parts) < 2:
            return None

        suffix = "::" + "::".join(parts[-2:]) if len(parts) >= 3 else "::" + parts[-1]
        matches = [k for k in self.durations if k.endswith(suffix)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logger.warning(
                "  Ambiguous suffix match for %s — %d candidates, skipping", junit_test_id[:60], len(matches)
            )
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


def run_merge_files(input_files: list[Path], output_file: Path) -> None:
    """Merge mode: outlier-merge already-merged per-segment files into one output.

    Fails loudly if no inputs survive — silently emitting an empty file would
    let a botched timing-update workflow commit an empty .test_durations to
    master, wiping the sharding signal everywhere downstream.
    """
    sources: list[dict[str, float]] = []
    for path in input_files:
        if not path.exists():
            logger.info("  skipping missing input %s", path)
            continue
        with open(path) as f:
            sources.append(json.load(f))
    if not sources:
        logger.error("No input files found to merge — refusing to write empty %s", output_file)
        sys.exit(1)

    merged = outlier_merge_durations(sources)
    with open(output_file, "w") as f:
        json.dump(merged, f, indent=4, sort_keys=True)
        f.write("\n")
    logger.info("Merged %d tests across %d segment(s) into %s", len(merged), len(sources), output_file)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Prepare test durations for pytest-split sharding")
    parser.add_argument("artifacts_dir", type=Path, nargs="?", help="Directory containing timing artifacts")
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
    parser.add_argument(
        "--merge-files",
        type=Path,
        nargs="+",
        default=None,
        help="Merge mode: outlier-merge the given duration files and write to output_file. "
        "Ignores artifacts_dir and the other artifact-processing flags.",
    )

    args = parser.parse_args()

    if args.merge_files:
        run_merge_files(args.merge_files, args.output_file)
        return

    if args.artifacts_dir is None:
        parser.error("artifacts_dir is required unless --merge-files is given")

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
