"""Tests for the outlier-merge logic in optimize_test_durations.

Run with: uv run --with pytest --with defusedxml pytest .github/scripts/test_optimize_test_durations.py
"""

import pytest

from optimize_test_durations import _pick_outlier, outlier_merge_durations


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
