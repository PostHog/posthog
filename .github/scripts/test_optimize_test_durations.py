"""Tests for the outlier-merge logic in optimize_test_durations.

Run with: uv run --with pytest --with defusedxml pytest .github/scripts/test_optimize_test_durations.py
"""

import sys
import json
from pathlib import Path

import pytest

from optimize_test_durations import (
    JUnitShard,
    MigrationTaxCorrector,
    ShardTimings,
    _pick_outlier,
    average_durations,
    drifting_shards,
    main,
    outlier_merge_durations,
    run_average_files,
    run_merge_files,
    scale_products_to_junit,
    scope_products_to_junit,
    shard_clock_coverage,
    shard_map_clock_ratios,
    shard_sets_match,
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

    def test_segment_with_no_artifacts_refuses_to_write(self, tmp_path, monkeypatch):
        # A run whose artifacts failed to download must not produce an empty durations
        # file: it would contribute nothing to the union and drag a multi-run product
        # average toward zero, un-sizing every product in it.
        out = tmp_path / "products_durations"
        monkeypatch.setattr(
            sys, "argv", ["optimize_test_durations.py", str(tmp_path), str(out), "--segment", "Products"]
        )
        with pytest.raises(SystemExit):
            main()
        assert not out.exists()

    @pytest.mark.parametrize(
        "shard_two_uploads",
        [
            {},
            {"junit-results-backend-core-2": b"<testsuite><testcase"},
            {
                "junit-results-backend-core-2": _MIN_JUNIT_XML,
                "junit-results-backend-core-2-attempt2": b"<testsuite><testcase",
            },
        ],
    )
    def test_scope_to_junit_refuses_a_shard_without_readable_junit(self, tmp_path, monkeypatch, shard_two_uploads):
        # Shard 2's JUnit never uploaded, uploaded truncated, or reran with a
        # truncated attempt on top of a good one. Scoping to what parsed would
        # drop nodeids shard 2 owns, so the script must exit and let the
        # workflow retry unscoped.
        artifacts = tmp_path / "timing_artifacts"
        for shard, test_id in (
            ("1", "posthog/test_foo.py::TestThing::test_one"),
            ("2", "posthog/test_bar.py::test_two"),
        ):
            shard_dir = artifacts / f"timing_data-Core-{shard}"
            shard_dir.mkdir(parents=True)
            (shard_dir / ".test_durations").write_text(json.dumps({test_id: 1.0}))
        junit_dir = tmp_path / "junit_artifacts"
        (junit_dir / "junit-results-backend-core-1").mkdir(parents=True)
        (junit_dir / "junit-results-backend-core-1" / "junit.xml").write_bytes(_MIN_JUNIT_XML)
        for name, xml in shard_two_uploads.items():
            (junit_dir / name).mkdir()
            (junit_dir / name / "junit.xml").write_bytes(xml)
        out = tmp_path / "core_durations"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "optimize_test_durations.py",
                str(artifacts),
                str(out),
                "--segment",
                "Core",
                "--junit-dir",
                str(junit_dir),
                "--scope-to-junit",
            ],
        )
        with pytest.raises(SystemExit):
            main()
        assert not out.exists()

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
            "product-junit-results-1",
            "junit-results-dagster-1",
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

    def test_products_matches_product_junit_prefix(self, junit_dir: Path) -> None:
        (junit_dir / "product-junit-results-1" / "second.xml").write_bytes(
            b'<testsuite><testcase classname="products.tasks.test_two.TestThing" name="test_two" time="1.5"/></testsuite>'
        )

        shards = JUnitShard.load_all(junit_dir, segment="Products")

        assert [shard.name for shard in shards] == ["product-junit-results-1"]
        assert set(shards[0].call_times) == {
            "posthog/test_foo.py::TestThing::test_one",
            "products/tasks/test_two.py::TestThing::test_two",
        }

    def test_dagster_matches_junit_results_dagster_prefix(self, junit_dir: Path) -> None:
        names = {s.name for s in JUnitShard.load_all(junit_dir, segment="Dagster")}
        assert names == {"junit-results-dagster-1"}

    def test_rerun_attempt_supersedes_earlier_attempts(self, junit_dir: Path) -> None:
        # The fixture's core-1 dir has time=0.5; an attempt-2 rerun of the same
        # shard must replace it, not sit alongside or be dropped.
        shard = junit_dir / "junit-results-backend-core-1-attempt2"
        shard.mkdir()
        (shard / "junit.xml").write_bytes(
            b'<testsuite><testcase classname="posthog.test_foo.TestThing" name="test_one" time="1.5"/></testsuite>'
        )

        shards = JUnitShard.load_all(junit_dir, segment="Core")

        assert [shard.name for shard in shards] == ["junit-results-backend-core-1", "junit-results-backend-core-2"]
        base = next(shard for shard in shards if shard.name == "junit-results-backend-core-1")
        assert base.call_times["posthog/test_foo.py::TestThing::test_one"] == 1.5

    def test_rerun_attempt_keeps_tests_only_an_earlier_attempt_ran(self, junit_dir: Path) -> None:
        # A rerun without the pinned plan can reshard a test into a shard that is
        # not rerun, so attempt 2 of shard 1 no longer lists it. Its attempt-1
        # membership must survive or scoping drops a test that ran.
        shard = junit_dir / "junit-results-backend-core-1-attempt2"
        shard.mkdir()
        (shard / "junit.xml").write_bytes(
            b'<testsuite><testcase classname="posthog.test_bar" name="test_two" time="2.0"/></testsuite>'
        )

        base = next(
            s for s in JUnitShard.load_all(junit_dir, segment="Core") if s.name == "junit-results-backend-core-1"
        )

        assert base.call_times == {
            "posthog/test_foo.py::TestThing::test_one": 0.5,
            "posthog/test_bar.py::test_two": 2.0,
        }

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


def test_merge_files_replaces_stale_segment_entries(tmp_path: Path) -> None:
    previous = tmp_path / "previous.json"
    fresh = tmp_path / "fresh.json"
    output = tmp_path / "output.json"
    previous.write_text(json.dumps({"posthog/test.py::test_core": 1.0, "products/tasks/old.py::test_old": 90.0}))
    fresh.write_text(json.dumps({"products/tasks/new.py::test_new": 10.0}))

    run_merge_files([previous, fresh], output, replace_prefix="products/")

    assert json.loads(output.read_text()) == {
        "posthog/test.py::test_core": 1.0,
        "products/tasks/new.py::test_new": 10.0,
    }


def test_shard_sets_match_requires_every_junit_artifact() -> None:
    timings = [
        ShardTimings(name="timing_data-Products-1", durations={}),
        ShardTimings(name="timing_data-Products-2", durations={}),
    ]
    complete = [
        JUnitShard(name="product-junit-results-1", call_times={}),
        JUnitShard(name="product-junit-results-2", call_times={}),
    ]
    partial = [JUnitShard(name="product-junit-results-1", call_times={})]

    assert shard_sets_match(timings, complete)
    assert not shard_sets_match(timings, partial)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_scope_products_to_junit_keeps_products_the_run_skipped(tmp_path: Path) -> None:
    (tmp_path / "ran").mkdir()
    (tmp_path / "skipped").mkdir()
    durations = {
        "products/ran/test_a.py::test_kept": 1.0,
        "products/ran/test_a.py::test_stale": 2.0,
        "products/skipped/test_b.py::test_one": 3.0,
        "products/deleted/test_c.py::test_one": 4.0,
        "posthog/test_d.py::test_one": 5.0,
    }

    scoped = scope_products_to_junit(durations, {"products/ran/test_a.py::test_kept"}, products_dir=tmp_path)

    assert scoped == {
        "products/ran/test_a.py::test_kept": 1.0,
        "products/skipped/test_b.py::test_one": 3.0,
    }


def test_scale_products_to_junit_matches_sums_to_measured_work(tmp_path: Path) -> None:
    # Recorded call-only durations under-count the fixture-heavy product; junit
    # carries the real total. Scaling keeps relative weights, fixes the sum.
    shard = tmp_path / "product-junit-results-0"
    shard.mkdir()
    (shard / "junit-product-big_one.xml").write_bytes(
        b'<?xml version="1.0"?><testsuite name="pytest" time="310.0">'
        b'<testcase classname="products.big_one.backend.test_a.TestA" name="test_a" time="100.0"/>'
        b'<testcase classname="products.big_one.backend.test_a.TestA" name="test_b" time="200.0"/></testsuite>'
    )
    durations = {
        "products/big_one/backend/test_a.py::TestA::test_a": 10.0,
        "products/big_one/backend/test_a.py::TestA::test_b": 20.0,
        "posthog/test/test_x.py::test_x": 5.0,
    }

    scaled = scale_products_to_junit(durations, tmp_path)

    assert scaled["products/big_one/backend/test_a.py::TestA::test_a"] == pytest.approx(100.0)
    assert scaled["products/big_one/backend/test_a.py::TestA::test_b"] == pytest.approx(200.0)
    assert scaled["posthog/test/test_x.py::test_x"] == 5.0
    assert scaled["products/.junit-scaled"] == 1.0


def test_main_writes_sub_ten_millisecond_durations_as_recorded(tmp_path: Path, monkeypatch) -> None:
    # A global floor once rewrote every fast test as 10 ms. Tens of thousands of
    # parametrized tests really take 1 ms, so a shard of them planned at twice
    # its real length.
    shard_dir = tmp_path / "timing_artifacts" / "timing_data-Core-1"
    shard_dir.mkdir(parents=True)
    (shard_dir / ".test_durations").write_text(
        json.dumps({"posthog/test_foo.py::TestThing::test_one": 0.5, "posthog/test_foo.py::TestThing::test_two": 0.001})
    )
    junit_dir = tmp_path / "junit_artifacts" / "junit-results-backend-core-1"
    junit_dir.mkdir(parents=True)
    (junit_dir / "junit.xml").write_bytes(
        b'<?xml version="1.0"?><testsuite name="pytest">'
        b'<testcase classname="posthog.test_foo.TestThing" name="test_one" time="0.5"/>'
        b'<testcase classname="posthog.test_foo.TestThing" name="test_two" time="0.001"/></testsuite>'
    )
    out = tmp_path / "core_durations"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_test_durations.py",
            str(tmp_path / "timing_artifacts"),
            str(out),
            "--segment",
            "Core",
            "--junit-dir",
            str(tmp_path / "junit_artifacts"),
            "--fail-on-drift",
        ],
    )

    main()

    assert json.loads(out.read_text())["posthog/test_foo.py::TestThing::test_two"] == 0.001


@pytest.mark.parametrize("junit_shards_present", [(), ("1",), ("1", "2")])
def test_fail_on_drift_refuses_an_incomplete_junit_set(tmp_path: Path, monkeypatch, junit_shards_present) -> None:
    # No JUnit, JUnit for only one of two shards, or JUnit that shares no test
    # with the timing data (the XML here names test_foo, the timings test_1 and
    # test_2) would let the drift check pass on nothing; a strict run must
    # refuse so the workflow keeps the previous slice instead of caching an
    # unchecked one.
    artifacts = tmp_path / "timing_artifacts"
    for shard in ("1", "2"):
        shard_dir = artifacts / f"timing_data-Core-{shard}"
        shard_dir.mkdir(parents=True)
        (shard_dir / ".test_durations").write_text(json.dumps({f"posthog/test_{shard}.py::test_{shard}": 1.0}))
    junit_dir = tmp_path / "junit_artifacts"
    junit_dir.mkdir()
    for shard in junit_shards_present:
        (junit_dir / f"junit-results-backend-core-{shard}").mkdir()
        (junit_dir / f"junit-results-backend-core-{shard}" / "junit.xml").write_bytes(_MIN_JUNIT_XML)
    out = tmp_path / "core_durations"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_test_durations.py",
            str(artifacts),
            str(out),
            "--segment",
            "Core",
            "--junit-dir",
            str(junit_dir),
            "--fail-on-drift",
        ],
    )

    with pytest.raises(SystemExit):
        main()
    assert not out.exists()


@pytest.mark.parametrize(
    "mapped_seconds, drifts",
    [
        (110.0, False),  # a tenth over: run-to-run noise
        (250.0, True),  # the shape is wrong: tiny tests carrying phantom weight
        (40.0, True),  # the other direction: heavy tests under-counted
    ],
)
def test_shard_map_clock_ratio_flags_shape_drift(mapped_seconds: float, drifts: bool) -> None:
    shard = JUnitShard(name="product-junit-results-3", call_times={"products/p/backend/test_a.py::test_a": 100.0})
    durations = {"products/p/backend/test_a.py::test_a": mapped_seconds, "products/p/backend/test_b.py::test_b": 5.0}

    ratios = shard_map_clock_ratios(durations, [shard])

    # test_b never ran in this shard, so it does not count against the shard.
    assert ratios == {"product-junit-results-3": pytest.approx(mapped_seconds / 100.0)}
    assert bool(drifting_shards(ratios)) is drifts


def test_shard_clock_coverage_counts_only_tests_the_map_holds() -> None:
    # A test missing from the map drops out of the ratio on both sides, so the
    # ratio alone cannot see a partial artifact; coverage can.
    shard = JUnitShard(
        name="product-junit-results-3",
        call_times={"products/p/backend/test_a.py::test_a": 30.0, "products/p/backend/test_b.py::test_b": 70.0},
    )

    assert shard_clock_coverage({"products/p/backend/test_a.py::test_a": 31.0}, [shard]) == {
        "product-junit-results-3": pytest.approx(0.3)
    }


def test_scale_products_to_junit_leaves_products_without_junit_alone(tmp_path: Path) -> None:
    durations = {"products/other_one/backend/test_b.py::test_b": 7.0}

    scaled = scale_products_to_junit(durations, tmp_path)

    assert scaled["products/other_one/backend/test_b.py::test_b"] == 7.0
    # The marker still lands: an empty junit dir means no product ran, and the
    # sums for products that did not run are unchanged either way.
    assert scaled["products/.junit-scaled"] == 1.0
