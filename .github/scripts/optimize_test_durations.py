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

Jobs without a restored schema cache build the test DB in the "Migrate
test_posthog from scratch" workflow step, but when that step fails,
--reuse-db falls back to building it in-process and the walk is absorbed
into whichever test first touches the DB, inflating its recorded duration
and skewing pytest-split.
This script merges the per-shard artifacts, floors any test recorded far
above its JUnit call time (or sitting at a flat-default placeholder) back
to that call time, and outputs clean durations for balanced distribution.
"""

import re
import sys
import glob
import json
import logging
import argparse
import statistics
import subprocess
from collections import Counter, defaultdict
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
# setup. When the out-of-process migrate step fell back to in-pytest, the
# walk lands on whichever test first touches the DB (not reliably the first
# test in the file), so detect it by the call-time gap rather than by
# position. Migration/DB setup is hundreds of seconds; legit per-test setup
# is tens at most, so this separates them.
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


# Maps segment names to the JUnit artifact prefix used by ci-backend.yml.
_JUNIT_ARTIFACT_PREFIX = {
    "Core": "junit-results-backend-core",
    "CorePOE": "junit-results-backend-core-poe",
    "Temporal": "junit-results-backend-temporal",
    "Products": "product-junit-results",
    "Dagster": "junit-results-dagster",
}


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
    # An XML of this shard (any attempt) did not parse, so call_times is incomplete.
    unreadable: bool = False

    @classmethod
    def load_all(cls, junit_dir: Path, segment: str | None = None) -> list["JUnitShard"]:
        """Load JUnit XMLs and extract per-test call times from each shard.

        JUnit artifact dirs are named like "junit-results-backend-core-1".
        Segment match is anchored at the artifact prefix so "Core" doesn't
        accidentally pick up "core-poe" or any future "*-core-*" name, and
        "CorePOE" matches "core-poe" instead of the absent substring "corepoe".

        Re-run attempts upload as `<shard>-attempt<N>` (attempt 1 carries no
        suffix). Attempts of one shard merge into one entry under the base
        shard name, so downstream shard-set matching sees one entry per shard.
        The newest attempt's time wins for a test every attempt ran; a test
        only an earlier attempt ran stays, because a rerun without the pinned
        plan can reshard it into a shard that is not rerun at all.
        """
        # Group re-run attempt dirs by base shard name (attempt 1 is the
        # unsuffixed dir), oldest attempt first.
        by_base: dict[str, list[tuple[int, Path]]] = defaultdict(list)
        for shard_dir in sorted(junit_dir.iterdir()):
            if not shard_dir.is_dir():
                continue
            match = re.match(r"^(.*?)(?:-attempt(\d+))?$", shard_dir.name.lower())
            if not match:
                continue
            base, attempt_n = match.group(1), int(match.group(2) or 1)
            by_base[base].append((attempt_n, shard_dir))

        shards = []
        for base, attempts in sorted(by_base.items()):
            if segment:
                artifact_prefix = _JUNIT_ARTIFACT_PREFIX.get(segment, f"junit-results-backend-{segment.lower()}")
                # Anchor with `\d+$` so the Core prefix doesn't accidentally
                # eat core-poe-N (which also starts with junit-results-backend-core-).
                pattern = re.compile(rf"^{re.escape(artifact_prefix)}-\d+$")
                if not pattern.match(base):
                    continue

            call_times: dict[str, float] = {}
            found_xml = False
            unreadable = False
            for _attempt_n, shard_dir in sorted(attempts):
                attempt_times: dict[str, float] = {}
                for xml_file in sorted(shard_dir.glob("*.xml")):
                    found_xml = True
                    parsed = cls._parse_call_times(xml_file)
                    if parsed is None:
                        unreadable = True
                        continue
                    for test_id, call_time in parsed.items():
                        attempt_times[test_id] = max(attempt_times.get(test_id, 0.0), call_time)
                call_times.update(attempt_times)
            if not found_xml:
                continue
            shards.append(cls(name=base, call_times=call_times, unreadable=unreadable))

        return shards

    @staticmethod
    def _parse_call_times(xml_path: Path) -> dict[str, float] | None:
        """Extract {pytest_id: call_time} for every parseable testcase, None when the XML does not parse."""
        try:
            tree = ET.parse(xml_path)
        except ParseError as e:
            logger.warning("  Could not parse JUnit XML %s: %s", xml_path, e)
            return None
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

    When a job's out-of-process migrate step fails, --reuse-db builds the
    DB in-process and the walk lands on whichever test first touches the
    DB, inflating that test's recorded setup+call duration and skewing
    pytest-split's shard balancing. The outlier-merge then prefers that
    inflated value over the test's real one. Normally the walk happens in
    its own workflow step (or a cached schema is restored), so no test
    carries tax and both modes below are cheap no-ops.

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
        return MigrationTaxResult(
            corrected,
            migration_tax_seconds=avg_removed,
            carriers_found=len(removed),
        )

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
        false positives from genuinely slow tests. That guard is now the
        whole story on tax-free runs (the normal path migrates
        out-of-process): a genuine test above the threshold would be
        misread as a carrier and floored, so if one ever appears, raise
        the threshold or drop this mode rather than trusting it.
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


def shard_sets_match(timing_shards: list[ShardTimings], junit_shards: list[JUnitShard]) -> bool:
    timing_ids = {shard.name.rsplit("-", 1)[-1] for shard in timing_shards}
    junit_ids = {shard.name.rsplit("-", 1)[-1] for shard in junit_shards}
    return timing_ids == junit_ids


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


PRODUCTS_SCALED_MARKER = "products/.junit-scaled"


def product_junit_work(junit_dir: Path) -> dict[str, float]:
    """Sum raw testcase seconds per product module from junit-product-*.xml files.

    Product jobs run without junit_duration_report=call, so testcase times include
    fixture setup and teardown and track real runner work. Raw sum on purpose:
    JUnitShard._parse_call_times collapses repeated pytest ids (parametrize) to
    their max, which under-counts a total. Keys are product module dir names.
    """
    work: dict[str, float] = defaultdict(float)
    for xml_path in sorted(junit_dir.rglob("junit-product-*.xml")):
        module = xml_path.stem[len("junit-product-") :]
        try:
            tree = ET.parse(xml_path)
        except ParseError as e:
            logger.warning("  Could not parse product JUnit %s: %s", xml_path, e)
            continue
        for tc in tree.getroot().iter("testcase"):
            try:
                work[module] += float(tc.get("time") or 0.0)
            except ValueError:
                continue
    return dict(work)


def product_module(test_id: str) -> str | None:
    """The products/<module>/ directory a nodeid lives in, or None outside products/."""
    parts = test_id.split("/", 2)
    if parts[0] != "products" or len(parts) < 3:
        return None
    return parts[1]


def scope_products_to_junit(durations: dict[str, float], ran: set[str], products_dir: Path) -> dict[str, float]:
    """Keep the nodeids the product jobs ran, plus every product no job ran at all.

    A product a run skips (SKIP_PRODUCT_TESTS, the quarantine file) still has a
    complete shard set, so it reaches here with no entries in ran. Dropping it
    would make the products/ replace-merge forget its timings, and once the skip
    lifts it sizes from the per-file fallback until the next run. A product whose
    directory is gone is stale, not skipped, so it is dropped.
    """
    ran_modules = {module for module in map(product_module, ran) if module}
    absent_modules = {module for module in map(product_module, durations) if module} - ran_modules
    skipped_modules = {module for module in absent_modules if (products_dir / module).is_dir()}
    return {
        test_id: duration
        for test_id, duration in durations.items()
        if test_id in ran or product_module(test_id) in skipped_modules
    }


def scale_products_to_junit(durations: dict[str, float], junit_dir: Path) -> dict[str, float]:
    """Scale each product's entries so their sum equals the JUnit-measured work.

    The recorded durations are call-only, which under-reports fixture-heavy
    suites several-fold, and shard sizing reads these sums as magnitudes. Scaling
    per product keeps the relative weights pytest-split needs while making the
    sums track real runner work.
    Call this on a junit-scoped durations dict (the Products branch scopes first),
    so every prefixed entry is one the product job really ran — suites another job
    records under the same prefix (a product's temporal tests running in the
    Django Temporal segment) are already scoped away and keep their own values in
    the union merge. Writes PRODUCTS_SCALED_MARKER so turbo-discover.js knows the
    sums are trustworthy; the marker key is not a real file and is ignored by
    pytest-split.
    """
    junit_work = product_junit_work(junit_dir)
    scaled = dict(durations)
    for module, target in sorted(junit_work.items()):
        prefix = f"products/{module}/"
        keys = [k for k in scaled if k.startswith(prefix)]
        current = sum(scaled[k] for k in keys)
        if current <= 0 or target <= 0:
            continue
        factor = target / current
        for k in keys:
            scaled[k] *= factor
        if abs(factor - 1) > 0.05:
            logger.info("  Scaled %s by %.2fx to junit work %.1f min", module, factor, target / 60)
    scaled[PRODUCTS_SCALED_MARKER] = 1.0
    return scaled


def run_merge_files(input_files: list[Path], output_file: Path, replace_prefix: str | None = None) -> None:
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

    if replace_prefix and len(sources) > 1:
        sources[0] = {
            test_id: duration for test_id, duration in sources[0].items() if not test_id.startswith(replace_prefix)
        }
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
    parser.add_argument(
        "--replace-prefix",
        default=None,
        help="In merge mode, remove matching entries from the first input before merging fresh segment data.",
    )

    args = parser.parse_args()

    if args.merge_files:
        run_merge_files(args.merge_files, args.output_file, args.replace_prefix)
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
    if not shards:
        # Same guard as run_merge_files/run_average_files: an empty durations file is
        # worse than no file. It contributes nothing to the union merge, so every
        # product the missing segment covers silently sizes to zero and gets packed
        # into a bucket it then runs straight past.
        logger.error(
            "No timing artifacts for segment %s in %s — refusing to write an empty durations file",
            args.segment or "all",
            args.artifacts_dir,
        )
        sys.exit(1)

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
        # A timing shard whose JUnit never uploaded, or uploaded truncated (the
        # parser turns that into an empty shard), would read as "nothing ran" and
        # lose every nodeid it owns, so scoping needs one readable JUnit per
        # shard. The workflow retries unscoped on this exit.
        unreadable = [shard.name for shard in junit_shards if shard.unreadable or not shard.call_times]
        if not shard_sets_match(shards, junit_shards) or unreadable:
            logger.error("--scope-to-junit needs a readable JUnit artifact for every timing shard: %s", unreadable)
            sys.exit(1)
        ran = set().union(*(s.call_times.keys() for s in junit_shards))
        before_count = len(durations)
        durations = {k: v for k, v in durations.items() if k in ran}
        logger.info(
            "  Scoped to %d nodeids the JUnit saw run (dropped %d cross-segment/stale)",
            len(durations),
            before_count - len(durations),
        )

    if args.segment == "Products" and junit_shards:
        if shard_sets_match(shards, junit_shards):
            ran = set().union(*(shard.call_times.keys() for shard in junit_shards))
            before_count = len(durations)
            durations = scope_products_to_junit(durations, ran, Path("products"))
            logger.info(
                "  Scoped Products to complete JUnit coverage (%d shards, dropped %d stale nodeids)",
                len(junit_shards),
                before_count - len(durations),
            )
            # Scaling needs the scoped dict: prefix-wide scaling is then exactly
            # "entries this product's job ran".
            durations = scale_products_to_junit(durations, args.junit_dir)
        else:
            logger.warning(
                "Product JUnit coverage incomplete; retaining unscoped timings — sums stay call-only undercounts"
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
