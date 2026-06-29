"""Tests for the outlier-merge logic in optimize_test_durations.

Run with: uv run --with pytest --with defusedxml pytest .github/scripts/test_optimize_test_durations.py
"""

from pathlib import Path

import pytest

from optimize_test_durations import (
    JUnitShard,
    MigrationTaxCorrector,
    _pick_outlier,
    average_durations,
    outlier_merge_durations,
    run_average_files,
)

# Minimal valid JUnit XML — one testcase with a CamelCase classname so
# _junit_to_pytest_id resolves cleanly.
_MIN_JUNIT_XML = b"""<?xml version="1.0"?>
<testsuite name="pytest"><testcase classname="posthog.test_foo.TestThing" name="test_one" time="0.5"/></testsuite>
"""


class TestPickOutlier:
    def test_all_same_returns_value(self):
        assert _pick_outlier([3.0, 3.0, 3.0]) == 3.0

    def test_single_outlier_against_majority(self):
        # 4 shards agree on 1.0 (stale passthrough), 1 reports 5.0 (fresh).
        # Outlier wins.
        assert _pick_outlier([1.0, 1.0, 5.0, 1.0, 1.0]) == 5.0

    def test_outlier_position_does_not_matter(self):
        assert _pick_outlier([5.0, 1.0, 1.0, 1.0, 1.0]) == 5.0
        assert _pick_outlier([1.0, 1.0, 1.0, 1.0, 5.0]) == 5.0

    def test_no_clear_majority_returns_an_outlier(self):
        # 2-2 tie: most_common picks one arbitrarily, outlier is the other.
        result = _pick_outlier([1.0, 1.0, 5.0, 5.0])
        assert result in (1.0, 5.0)

    def test_single_value(self):
        assert _pick_outlier([7.0]) == 7.0


class TestOutlierMergeDurations:
    def test_empty_input(self):
        assert outlier_merge_durations([]) == {}

    def test_single_source_passthrough(self):
        source = {"test_a": 1.5, "test_b": 2.5}
        assert outlier_merge_durations([source]) == source

    def test_merge_picks_outlier_per_test(self):
        # Three "segments". test_a: fresh in segment 0; test_b: fresh in segment 2.
        sources = [
            {"test_a": 5.0, "test_b": 1.0},
            {"test_a": 1.0, "test_b": 1.0},
            {"test_a": 1.0, "test_b": 9.0},
        ]
        merged = outlier_merge_durations(sources)
        assert merged == {"test_a": 5.0, "test_b": 9.0}

    def test_test_present_in_only_one_source(self):
        # A new test that only one segment knows about — kept with its value.
        sources = [
            {"test_a": 1.0, "test_b": 1.0},
            {"test_a": 1.0, "test_b": 1.0, "new_test": 4.2},
        ]
        merged = outlier_merge_durations(sources)
        assert merged["new_test"] == 4.2

    def test_all_segments_agree_keeps_value(self):
        sources = [
            {"test_a": 1.0},
            {"test_a": 1.0},
            {"test_a": 1.0},
        ]
        assert outlier_merge_durations(sources) == {"test_a": 1.0}


class TestAverageDurations:
    def test_empty_input(self):
        assert average_durations([]) == {}

    def test_single_source_passthrough(self):
        source = {"test_a": 1.5, "test_b": 2.5}
        assert average_durations([source]) == source

    def test_mean_across_runs(self):
        sources = [
            {"test_a": 2.0, "test_b": 10.0},
            {"test_a": 4.0, "test_b": 20.0},
        ]
        assert average_durations(sources) == {"test_a": 3.0, "test_b": 15.0}

    def test_median_resists_a_stray_run(self):
        # test_a spikes in one run (e.g. residual contamination); median ignores
        # it where mean would drag toward the spike.
        sources = [{"test_a": 2.0}, {"test_a": 2.0}, {"test_a": 100.0}]
        assert average_durations(sources, strategy="median") == {"test_a": 2.0}

    def test_membership_anchored_to_first_source(self):
        # 'deleted' only appears in an older (non-first) run -> dropped.
        # 'added' only appears in the first (latest) run -> kept.
        sources = [
            {"test_a": 1.0, "added": 3.0},
            {"test_a": 1.0, "deleted": 9.0},
        ]
        result = average_durations(sources)
        assert "deleted" not in result
        assert result["added"] == 3.0

    def test_average_over_present_runs_only(self):
        # test_a measured in 2 of 3 runs; average over just those two.
        sources = [{"test_a": 2.0}, {"test_b": 5.0}, {"test_a": 6.0}]
        assert average_durations(sources)["test_a"] == 4.0

    def test_run_average_files_refuses_empty_result(self, tmp_path):
        # Newest (anchor) run scoped to nothing must not silently wipe the plan,
        # even when older runs still carry data — refuse to write, don't emit {}.
        newest = tmp_path / "core_newest"
        newest.write_text("{}")
        older = tmp_path / "core_older"
        older.write_text('{"test_a": 1.0}')
        out = tmp_path / "out.core"
        with pytest.raises(SystemExit):
            run_average_files([newest, older], out)
        assert not out.exists()


class TestJUnitShardSegmentFilter:
    """Pin the segment-prefix anchoring so `Core` can't eat `core-poe-N`."""

    @pytest.fixture
    def junit_dir(self, tmp_path: Path) -> Path:
        for name in (
            "junit-results-backend-core-1",
            "junit-results-backend-core-2",
            "junit-results-backend-core-poe-1",
            "junit-results-backend-temporal-1",
            "junit-results-backend-compat-1",  # unrelated, shouldn't match anything
        ):
            shard = tmp_path / name
            shard.mkdir()
            (shard / "junit.xml").write_bytes(_MIN_JUNIT_XML)
        return tmp_path

    def test_core_does_not_match_core_poe(self, junit_dir: Path):
        names = {s.name for s in JUnitShard.load_all(junit_dir, segment="Core")}
        assert names == {"junit-results-backend-core-1", "junit-results-backend-core-2"}

    def test_corepoe_matches_core_poe(self, junit_dir: Path):
        names = {s.name for s in JUnitShard.load_all(junit_dir, segment="CorePOE")}
        assert names == {"junit-results-backend-core-poe-1"}

    def test_temporal_only_matches_temporal(self, junit_dir: Path):
        names = {s.name for s in JUnitShard.load_all(junit_dir, segment="Temporal")}
        assert names == {"junit-results-backend-temporal-1"}

    def test_unknown_segment_does_not_panic(self, junit_dir: Path):
        # Unknown segments fall back to lowercase passthrough — should just
        # match nothing in this fixture, not crash.
        assert JUnitShard.load_all(junit_dir, segment="Bogus") == []


class TestJUnitCallTimeCorrection:
    """JUnit call time is ground truth — floor contaminated / placeholder values."""

    @staticmethod
    def _shard(name: str, call_times: dict[str, float]) -> JUnitShard:
        return JUnitShard(name=name, call_times=call_times)

    def test_floors_migration_tax_contamination(self):
        # Tax landed on a non-first test: recorded 408s, real call 4.3s.
        durations = {"posthog/x.py::T::test_a": 408.0, "posthog/x.py::T::test_b": 2.0}
        shards = [self._shard("core-1", {"posthog/x.py::T::test_a": 4.3, "posthog/x.py::T::test_b": 2.0})]
        result = MigrationTaxCorrector(durations, junit_shards=shards).correct()
        assert result.corrected_durations["posthog/x.py::T::test_a"] == 4.3
        assert result.corrected_durations["posthog/x.py::T::test_b"] == 2.0
        assert result.carriers_found == 1

    def test_floors_flat_default_placeholder(self):
        # 60.0 is a pytest-split placeholder; JUnit knows the real call time.
        durations = {"posthog/x.py::T::test_a": 60.0}
        shards = [self._shard("core-1", {"posthog/x.py::T::test_a": 0.5})]
        result = MigrationTaxCorrector(durations, junit_shards=shards).correct()
        assert result.corrected_durations["posthog/x.py::T::test_a"] == 0.5

    def test_leaves_genuinely_slow_test_untouched(self):
        # Real end-to-end test: recorded ~= call, small gap, not flooded.
        durations = {"posthog/x.py::T::test_slow": 102.0}
        shards = [self._shard("core-1", {"posthog/x.py::T::test_slow": 101.5})]
        result = MigrationTaxCorrector(durations, junit_shards=shards).correct()
        assert result.corrected_durations["posthog/x.py::T::test_slow"] == 102.0
        assert result.carriers_found == 0

    def test_leaves_gray_zone_setup_untouched(self):
        # Recorded 42s, call 1s: 41s gap is below the 120s tax threshold and
        # not a flat default, so it's treated as legit setup and kept.
        durations = {"posthog/x.py::T::test_setup_heavy": 42.0}
        shards = [self._shard("core-1", {"posthog/x.py::T::test_setup_heavy": 1.0})]
        result = MigrationTaxCorrector(durations, junit_shards=shards).correct()
        assert result.corrected_durations["posthog/x.py::T::test_setup_heavy"] == 42.0

    def test_keeps_high_recorded_test_with_small_gap(self):
        # Above the 120s threshold (so it passes the short-circuit) but the
        # gap to call time is small — a genuinely slow test, not a carrier.
        # Exercises the inner false-positive guard the short-circuit hides.
        durations = {"posthog/x.py::T::test_slow": 150.0}
        shards = [self._shard("core-1", {"posthog/x.py::T::test_slow": 140.0})]
        result = MigrationTaxCorrector(durations, junit_shards=shards).correct()
        assert result.corrected_durations["posthog/x.py::T::test_slow"] == 150.0
        assert result.carriers_found == 0

    def test_function_style_name_not_floored_when_ambiguous(self):
        # A bare function name shared across files must not match by suffix —
        # ambiguous lookups return None, so the value is left untouched.
        durations = {"products/a/test_x.py::test_run": 408.0}
        shards = [
            self._shard("core-1", {"products/b/test_y.py::test_run": 1.0}),
            self._shard("core-2", {"products/c/test_z.py::test_run": 1.0}),
        ]
        result = MigrationTaxCorrector(durations, junit_shards=shards).correct()
        assert result.corrected_durations["products/a/test_x.py::test_run"] == 408.0

    def test_suffix_match_when_path_prefix_differs(self):
        # durations key has a path prefix the JUnit id lacks — suffix match.
        durations = {"posthog/api/test/x.py::T::test_a": 408.0}
        shards = [self._shard("core-1", {"api/test/x.py::T::test_a": 3.0})]
        result = MigrationTaxCorrector(durations, junit_shards=shards).correct()
        assert result.corrected_durations["posthog/api/test/x.py::T::test_a"] == 3.0

    def test_no_junit_match_leaves_value(self):
        # No JUnit entry for the test — can't verify, so keep the value.
        durations = {"posthog/x.py::T::test_a": 408.0}
        shards = [self._shard("core-1", {"posthog/x.py::T::test_other": 1.0})]
        result = MigrationTaxCorrector(durations, junit_shards=shards).correct()
        assert result.corrected_durations["posthog/x.py::T::test_a"] == 408.0


class TestStatisticalCorrection:
    """No JUnit (Products): fall back to top-N outlier carriers."""

    def test_subtracts_average_tax_from_outliers(self):
        durations = {f"t{i}": 1.0 for i in range(10)}
        durations["t0"] = 410.0  # one carrier
        result = MigrationTaxCorrector(durations, expected_shard_count=1).correct()
        # carrier floored toward its real (small) value after tax subtraction
        assert result.corrected_durations["t0"] < 410.0
        assert result.carriers_found == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
