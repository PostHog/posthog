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

Merges timing artifacts from CI shards and removes migration-tax
contamination using JUnit call times as a setup-free contamination signal.

Under --reuse-db the per-shard Django DB build (~7 min on master) is
absorbed into whichever test first touches the DB, inflating its recorded
duration and skewing pytest-split. This script merges the per-shard
artifacts, floors any test recorded far above its JUnit call time (or
sitting at a flat-default placeholder) back to that call time, and outputs
clean durations for balanced distribution.
"""

import re
import sys
import glob
import json
import logging
import argparse
import statistics
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
# A test recorded this far above its JUnit call time absorbed per-shard DB
# setup. Under --reuse-db the migration walk lands on whichever test first
# touches the DB (not reliably the first test in the file), so detect it by
# the call-time gap rather than by position. Migration/DB setup is hundreds
# of seconds; legit per-test setup is tens at most, so this separates them.
MIGRATION_TAX_THRESHOLD_SECONDS = 120.0
# pytest-split writes these flat values for tests it has no timing for. They
# are placeholders, not measurements — when JUnit has a real call time for
# the test, prefer that. See reference: .test_durations ships 60.0 / 18.0.
DEFAULT_PLACEHOLDER_SECONDS = (60.0, 18.0)


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
    """JUnit call-time data from a single CI shard.

    XMLs are produced with `-o junit_duration_report=call`, so each
    testcase's `time` is call time only — no fixture setup/teardown. The gap
    between a test's recorded total and its call time is a reliable signal of
    setup contamination (the migration walk shows up as a huge phantom gap),
    used to detect and undo it in the merged .test_durations.
    """

    name: str
    call_times: dict[str, float]

    @classmethod
    def load_all(cls, junit_dir: Path, segment: str | None = None) -> list["JUnitShard"]:
        """Load JUnit XMLs and extract per-test call times from each shard.

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

            shards.append(cls(name=shard_dir.name, call_times=cls._parse_call_times(xml_files[0])))

        return shards

    @staticmethod
    def _parse_call_times(xml_path: Path) -> dict[str, float]:
        """Extract {pytest_id: call_time} for every parseable testcase."""
        try:
            tree = ET.parse(xml_path)
        except ParseError as e:
            logger.warning("  Could not parse JUnit XML %s: %s", xml_path, e)
            return {}
        call_times: dict[str, float] = {}
        for tc in tree.getroot().iter("testcase"):
            pytest_id = _junit_to_pytest_id(tc.get("classname", ""), tc.get("name", ""))
            time = tc.get("time")
            if not pytest_id or time is None:
                continue
            try:
                value = float(time)
            except ValueError:
                continue
            # Keep the largest if a test id appears more than once (parametrize).
            call_times[pytest_id] = max(call_times.get(pytest_id, 0.0), value)
        return call_times


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


def average_durations(sources: list[dict[str, float]], strategy: str = "mean") -> dict[str, float]:
    """Combine N already-merged, de-taxed per-RUN duration vectors into one.

    Different from outlier_merge_durations: that picks the fresh value among a
    single run's stale shard passthroughs. This one assumes every input is a
    clean per-run vector and averages a test across runs. A single run's per-test
    times are noisy and the file-granularity plan chases that noise; averaging the
    last few runs damps it (measured ~-8pp makespan/mean on real PRs going 1 -> 5
    runs, with the floor itself near 0%).

    Membership is anchored to the FIRST source -- pass the LATEST run first -- so a
    test deleted since an older run never lingers in the plan, while each surviving
    test is averaged only over the runs that actually measured it. ``mean`` is the
    validated default; ``median`` is offered for extra robustness to a stray run.
    """
    if not sources:
        return {}
    aggregate = statistics.median if strategy == "median" else statistics.fmean
    anchor = sources[0]
    return {test: aggregate([s[test] for s in sources if test in s]) for test in anchor}


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
    """Removes migration-tax contamination from merged durations.

    Under --reuse-db the per-shard Django DB build (~7 min on master) lands
    on whichever test first touches the DB, inflating that test's recorded
    setup+call duration and skewing pytest-split's shard balancing. The
    outlier-merge then prefers that inflated value over the test's real one.

    Two modes:
    - JUnit-based (preferred): JUnit call time is the call phase only, so a
      test recorded far above it absorbed setup tax. Floor such tests (and
      pytest-split flat-default placeholders) to the call time. This under-
      counts a carrier's own real setup, but that's small and unrecoverable
      post-merge, so it's a safe conservative floor. Location-independent —
      catches the tax wherever it lands, not just on the first test. Risk: a
      test with genuinely heavy (>threshold) setup would be wrongly floored;
      none observed, and every floor is logged.
    - Statistical fallback: when JUnit is unavailable (Products), identify
      the N highest-duration outliers (one carrier per shard) and subtract
      the average tax. Coarser, but no per-test call time exists there.
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
            return self._correct_from_junit()
        if self.expected_shard_count > 0:
            return self._correct_statistically()
        logger.info("  No JUnit data or shard count — skipping carrier correction")
        return MigrationTaxResult(dict(self.durations), migration_tax_seconds=0, carriers_found=0)

    def _correct_from_junit(self) -> MigrationTaxResult:
        """Floor contaminated / placeholder durations to their JUnit call time."""
        junit_call: dict[str, float] = {}
        for shard in self.junit_shards:
            for test_id, call in shard.call_times.items():
                junit_call[test_id] = max(junit_call.get(test_id, 0.0), call)

        corrected = dict(self.durations)
        removed: list[float] = []
        for test_id, recorded in self.durations.items():
            is_placeholder = any(abs(recorded - d) < 1e-3 for d in DEFAULT_PLACEHOLDER_SECONDS)
            could_be_contaminated = recorded > MIGRATION_TAX_THRESHOLD_SECONDS
            # Cheap short-circuit: only the high or placeholder values can be
            # bad, so skip the suffix lookup for the ~58k healthy small ones.
            if not (is_placeholder or could_be_contaminated):
                continue

            call = self._lookup_call_time(test_id, junit_call)
            if call is None or call >= recorded:
                continue

            contaminated = could_be_contaminated and recorded - call > MIGRATION_TAX_THRESHOLD_SECONDS
            if not (contaminated or is_placeholder):
                continue

            corrected[test_id] = max(MIN_DURATION, call)
            removed.append(recorded - call)
            reason = "migration tax" if contaminated else "flat-default"
            logger.info("  De-taxed %s: %.0fs -> %.1fs (%s, junit call)", test_id[:60], recorded, call, reason)

        avg_removed = sum(removed) / len(removed) if removed else 0.0
        if removed:
            logger.info(
                "  De-taxed %d tests via JUnit, avg removed %.0fs (%.1fm)", len(removed), avg_removed, avg_removed / 60
            )
        else:
            logger.info("  No JUnit-detected contamination")
        return MigrationTaxResult(corrected, migration_tax_seconds=avg_removed, carriers_found=len(removed))

    @staticmethod
    def _lookup_call_time(test_id: str, junit_call: dict[str, float]) -> float | None:
        """Find a durations key's call time in the JUnit map.

        Exact match first; otherwise a suffix anchored on the file basename
        (`file.py::[Class::]test`) at a path boundary, accepted only when
        unique — JUnit ids and pytest node ids can differ only in directory
        prefix. Anchoring on the basename keeps a bare function name from
        colliding across files. Only ever called for the handful of high /
        placeholder durations, so the linear scan is cheap.
        """
        if test_id in junit_call:
            return junit_call[test_id]
        parts = test_id.split("::")
        if len(parts) < 2:
            return None
        tail = "::".join([parts[0].rsplit("/", 1)[-1], *parts[1:]])
        matches = [v for k, v in junit_call.items() if k == tail or k.endswith("/" + tail)]
        return matches[0] if len(matches) == 1 else None

    def _correct_statistically(self) -> MigrationTaxResult:
        carriers = self._find_carriers_statistically()
        if not carriers:
            logger.info("  No migration carriers found")
            return MigrationTaxResult(dict(self.durations), migration_tax_seconds=0, carriers_found=0)
        migration_tax = self._estimate_tax(carriers)
        return MigrationTaxResult(
            corrected_durations=self._apply_correction(carriers, migration_tax),
            migration_tax_seconds=migration_tax,
            carriers_found=len(carriers),
        )

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


def run_average_files(input_files: list[Path], output_file: Path, strategy: str = "mean") -> None:
    """Average mode: combine already-merged per-RUN files into one output.

    Pass the LATEST run's file first -- membership anchors to it. Fails loudly if
    no inputs survive, same guard as run_merge_files: an empty per-segment file
    would silently un-balance every PR's file-mode shards.
    """
    sources: list[dict[str, float]] = []
    for path in input_files:
        if not path.exists():
            logger.info("  skipping missing input %s", path)
            continue
        with open(path) as f:
            sources.append(json.load(f))
    if not sources:
        logger.error("No input files found to average — refusing to write empty %s", output_file)
        sys.exit(1)

    averaged = average_durations(sources, strategy=strategy)
    # Membership anchors to the first (newest) source, so an empty newest file would
    # empty the whole result even when older runs carry data. Refuse to write it —
    # the workflow's `|| echo warning` then leaves file-mode to scope the union.
    if not averaged:
        logger.error("Averaged durations are empty (newest run scoped to nothing?) — refusing to write %s", output_file)
        sys.exit(1)

    with open(output_file, "w") as f:
        json.dump(averaged, f, indent=4, sort_keys=True)
        f.write("\n")
    logger.info("Averaged %d tests across %d run(s) [%s] into %s", len(averaged), len(sources), strategy, output_file)


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
        "--scope-to-junit",
        action="store_true",
        help=(
            "Filter the output to exactly the nodeids the JUnit artifacts saw run "
            "(requires --junit-dir). The shared .test_durations is a union across all "
            "CI jobs, so a segment's artifacts still carry stale cross-segment nodeids "
            "(other segments' param variants, product-routed files). This scopes a "
            "per-segment file to what THAT segment actually ran -- the run-set is already "
            "in the JUnit, so no extra collection is needed. Used to emit "
            ".test_durations.<segment> for --split-granularity=file."
        ),
    )
    parser.add_argument(
        "--merge-files",
        type=Path,
        nargs="+",
        default=None,
        help="Merge mode: outlier-merge the given duration files and write to output_file. "
        "Ignores artifacts_dir and the other artifact-processing flags.",
    )
    parser.add_argument(
        "--average-files",
        type=Path,
        nargs="+",
        default=None,
        help="Average mode: combine already-merged per-RUN duration files (LATEST first) into "
        "output_file by per-test mean/median. Builds a multi-run .test_durations.<segment> that "
        "is robust to one run's timing noise. Ignores artifacts_dir.",
    )
    parser.add_argument(
        "--average-strategy",
        choices=["mean", "median"],
        default="mean",
        help="Aggregation for --average-files (default: mean).",
    )

    args = parser.parse_args()

    if args.merge_files:
        run_merge_files(args.merge_files, args.output_file)
        return

    if args.average_files:
        run_average_files(args.average_files, args.output_file, args.average_strategy)
        return

    if args.artifacts_dir is None:
        parser.error("artifacts_dir is required unless --merge-files or --average-files is given")

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

    # Scope to exactly what this segment's JUnit saw run. The shared timing
    # artifacts each carry the full union (every shard restores the merged file
    # then refreshes its own slice), so a per-segment merge still contains other
    # segments' nodeids -- their param variants and product-routed files -- which
    # would poison a file-granularity plan (it budgets weight for tests that never
    # collect in this segment). The JUnit call_times map is the segment's real
    # run-set at nodeid granularity, already loaded above, so this costs nothing.
    if args.scope_to_junit:
        if not junit_shards:
            logger.error("--scope-to-junit requires --junit-dir with matching artifacts")
            sys.exit(1)
        ran = set().union(*(s.call_times.keys() for s in junit_shards))
        before_count = len(durations)
        durations = {k: v for k, v in durations.items() if k in ran}
        logger.info(
            "  Scoped to %d nodeids the JUnit saw run (dropped %d cross-segment/stale)",
            len(durations),
            before_count - len(durations),
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
