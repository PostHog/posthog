"""Tests for the outlier-merge logic in optimize_test_durations.

Run with: uv run --with pytest --with defusedxml pytest .github/scripts/test_optimize_test_durations.py
"""

from pathlib import Path

import pytest

from optimize_test_durations import JUnitShard, _pick_outlier, outlier_merge_durations

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
