import datetime as dt
from datetime import UTC, datetime

import unittest

from hypothesis import (
    given,
    settings,
    strategies as st,
)
from parameterized import parameterized

from products.alerts_platform.backend.facade.rolling_checks import (
    CHECKPOINT_MAX_STALENESS,
    CheckWindow,
    derive_breaches,
    resolve_check_end,
    rolling_check_ranges,
)


class TestResolveAlertDateTo(unittest.TestCase):
    NEXT_CHECK_AT = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_none_checkpoint_returns_next_check_at(self):
        assert resolve_check_end(self.NEXT_CHECK_AT, None) == self.NEXT_CHECK_AT

    def test_fresh_checkpoint_in_past_is_used(self):
        checkpoint = self.NEXT_CHECK_AT - dt.timedelta(seconds=30)
        assert resolve_check_end(self.NEXT_CHECK_AT, checkpoint) == checkpoint

    def test_checkpoint_equal_to_next_check_at_is_used(self):
        assert resolve_check_end(self.NEXT_CHECK_AT, self.NEXT_CHECK_AT) == self.NEXT_CHECK_AT

    def test_future_checkpoint_is_clamped_to_next_check_at(self):
        checkpoint = self.NEXT_CHECK_AT + dt.timedelta(seconds=60)
        assert resolve_check_end(self.NEXT_CHECK_AT, checkpoint) == self.NEXT_CHECK_AT

    def test_stale_checkpoint_beyond_threshold_falls_back_to_next_check_at(self):
        # The "quiet partition pins min() backwards" case — must not strand spikes
        # on active partitions in the past.
        checkpoint = self.NEXT_CHECK_AT - CHECKPOINT_MAX_STALENESS - dt.timedelta(seconds=1)
        assert resolve_check_end(self.NEXT_CHECK_AT, checkpoint) == self.NEXT_CHECK_AT

    def test_checkpoint_exactly_at_threshold_is_still_used(self):
        checkpoint = self.NEXT_CHECK_AT - CHECKPOINT_MAX_STALENESS
        assert resolve_check_end(self.NEXT_CHECK_AT, checkpoint) == checkpoint


class TestDeriveBreachesProperties(unittest.TestCase):
    @parameterized.expand([("gt",), ("ABOVE",), ("",)])
    def test_unknown_operator_raises(self, operator: str) -> None:
        with self.assertRaises(ValueError):
            derive_breaches([5], 1, operator, 1)

    @parameterized.expand([("above",), ("below",)])
    def test_a_window_with_no_data_never_breaches(self, operator: str) -> None:
        assert derive_breaches([None, 5, None], 1, operator, 3) == (False, operator == "above", False)

    @parameterized.expand([("above", 0, False), ("below", 0, False), ("below", 1, True)])
    def test_padding_is_the_outcome_of_a_zero_count(self, operator: str, threshold: int, expected: bool) -> None:
        assert derive_breaches([], threshold, operator, 3) == (expected,) * 3

    @given(
        bucket_counts=st.lists(st.integers(min_value=0, max_value=10_000), min_size=0, max_size=10),
        threshold=st.integers(min_value=1, max_value=5_000),
        operator=st.sampled_from(["above", "below"]),
    )
    @settings(max_examples=500, deadline=None)
    def test_length_preserved_when_no_padding_needed(
        self, bucket_counts: list[int], threshold: int, operator: str
    ) -> None:
        # When evaluation_periods == len(bucket_counts), no pad fires; result length
        # matches input. Padding behavior covered by a separate property below.
        result = derive_breaches(bucket_counts, threshold, operator, len(bucket_counts))
        assert len(result) == len(bucket_counts)

    @given(
        bucket_counts=st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=10),
        threshold=st.integers(min_value=1, max_value=5_000),
        operator=st.sampled_from(["above", "below"]),
    )
    @settings(max_examples=500, deadline=None)
    def test_newest_first_ordering(self, bucket_counts: list[int], threshold: int, operator: str) -> None:
        # The first element of the returned tuple corresponds to the LAST bucket
        # in the ASC input — i.e., the newest. State machine reads window
        # newest-first, so getting this wrong silently flips N-of-M decisions.
        result = derive_breaches(bucket_counts, threshold, operator, len(bucket_counts))
        newest_breach = bucket_counts[-1] > threshold if operator == "above" else bucket_counts[-1] < threshold
        assert result[0] == newest_breach

    @given(
        bucket_counts=st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=10),
        threshold=st.integers(min_value=1, max_value=5_000),
        operator=st.sampled_from(["above", "below"]),
    )
    @settings(max_examples=500, deadline=None)
    def test_breach_count_matches_threshold_predicate_when_no_padding(
        self, bucket_counts: list[int], threshold: int, operator: str
    ) -> None:
        # When the bucket list is already M long, no padding fires and the
        # breach count exactly matches the count of inputs satisfying the
        # threshold predicate. Catches drop / duplicate bugs.
        result = derive_breaches(bucket_counts, threshold, operator, len(bucket_counts))
        if operator == "above":
            expected_count = sum(1 for c in bucket_counts if c > threshold)
        else:
            expected_count = sum(1 for c in bucket_counts if c < threshold)
        assert sum(result) == expected_count

    @given(
        bucket_counts=st.lists(st.integers(min_value=1, max_value=10_000), min_size=1, max_size=10),
        threshold=st.integers(min_value=1, max_value=10_000),
    )
    @settings(max_examples=300, deadline=None)
    def test_above_and_below_are_complementary_at_strict_inequality(
        self, bucket_counts: list[int], threshold: int
    ) -> None:
        # `above` = count > threshold; `below` = count < threshold. For any count
        # ≠ threshold, exactly one of the two is True. Sum of breach counts across
        # the two operators equals the number of buckets that aren't EQ to threshold.
        above = derive_breaches(bucket_counts, threshold, "above", len(bucket_counts))
        below = derive_breaches(bucket_counts, threshold, "below", len(bucket_counts))
        not_equal = sum(1 for c in bucket_counts if c != threshold)
        assert sum(above) + sum(below) == not_equal

    @given(
        bucket_counts=st.lists(st.integers(min_value=0, max_value=10_000), min_size=0, max_size=5),
        threshold=st.integers(min_value=1, max_value=5_000),
        m_extra=st.integers(min_value=1, max_value=8),
    )
    @settings(max_examples=300, deadline=None)
    def test_padding_fills_to_evaluation_periods_with_correct_implicit_breach(
        self, bucket_counts: list[int], threshold: int, m_extra: int
    ) -> None:
        # When `evaluation_periods > len(bucket_counts)`, the result is padded to length
        # M with the implicit count=0 outcome:
        #   - above: pad = False (0 is not above threshold)
        #   - below: pad = True (0 is below threshold, given threshold >= 1)
        # This is the load-bearing fix for `below` alerts on silent services —
        # without it, an empty bucket list yields no breaches and silence detection
        # would never fire.
        m = len(bucket_counts) + m_extra

        above = derive_breaches(bucket_counts, threshold, "above", m)
        below = derive_breaches(bucket_counts, threshold, "below", m)

        assert len(above) == m
        assert len(below) == m
        # The trailing `m_extra` entries are pure padding.
        assert above[len(bucket_counts) :] == (False,) * m_extra
        assert below[len(bucket_counts) :] == (True,) * m_extra


class TestRollingCheckRanges(unittest.TestCase):
    NCA = datetime(2026, 5, 3, 6, 0, 0, tzinfo=UTC)

    def test_m_equals_1_returns_single_latest_window(self):
        ranges = rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=1)
        assert ranges == [CheckWindow(start=self.NCA - dt.timedelta(minutes=15), end=self.NCA)]

    def test_m_equals_3_window_15_cadence_5(self):
        ranges = rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=3)
        assert ranges == [
            CheckWindow(start=datetime(2026, 5, 3, 5, 35, tzinfo=UTC), end=datetime(2026, 5, 3, 5, 50, tzinfo=UTC)),
            CheckWindow(start=datetime(2026, 5, 3, 5, 40, tzinfo=UTC), end=datetime(2026, 5, 3, 5, 55, tzinfo=UTC)),
            CheckWindow(start=datetime(2026, 5, 3, 5, 45, tzinfo=UTC), end=datetime(2026, 5, 3, 6, 0, tzinfo=UTC)),
        ]

    def test_m_equals_3_window_30_cadence_5(self):
        ranges = rolling_check_ranges(self.NCA, window_minutes=30, cadence_minutes=5, period_count=3)
        assert ranges == [
            CheckWindow(start=datetime(2026, 5, 3, 5, 20, tzinfo=UTC), end=datetime(2026, 5, 3, 5, 50, tzinfo=UTC)),
            CheckWindow(start=datetime(2026, 5, 3, 5, 25, tzinfo=UTC), end=datetime(2026, 5, 3, 5, 55, tzinfo=UTC)),
            CheckWindow(start=datetime(2026, 5, 3, 5, 30, tzinfo=UTC), end=datetime(2026, 5, 3, 6, 0, tzinfo=UTC)),
        ]

    def test_cadence_equals_window_produces_non_overlapping_back_to_back(self):
        ranges = rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=15, period_count=3)
        assert ranges == [
            CheckWindow(start=datetime(2026, 5, 3, 5, 15, tzinfo=UTC), end=datetime(2026, 5, 3, 5, 30, tzinfo=UTC)),
            CheckWindow(start=datetime(2026, 5, 3, 5, 30, tzinfo=UTC), end=datetime(2026, 5, 3, 5, 45, tzinfo=UTC)),
            CheckWindow(start=datetime(2026, 5, 3, 5, 45, tzinfo=UTC), end=datetime(2026, 5, 3, 6, 0, tzinfo=UTC)),
        ]

    def test_cadence_greater_than_window_produces_gaps(self):
        ranges = rolling_check_ranges(self.NCA, window_minutes=5, cadence_minutes=10, period_count=3)
        assert ranges == [
            CheckWindow(start=datetime(2026, 5, 3, 5, 35, tzinfo=UTC), end=datetime(2026, 5, 3, 5, 40, tzinfo=UTC)),
            CheckWindow(start=datetime(2026, 5, 3, 5, 45, tzinfo=UTC), end=datetime(2026, 5, 3, 5, 50, tzinfo=UTC)),
            CheckWindow(start=datetime(2026, 5, 3, 5, 55, tzinfo=UTC), end=datetime(2026, 5, 3, 6, 0, tzinfo=UTC)),
        ]

    def test_oldest_first_ordering(self):
        ranges = rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=5)
        starts = [window.start for window in ranges]
        assert starts == sorted(starts)

    @parameterized.expand(
        [
            ("M1", 1),
            ("M2", 2),
            ("M3", 3),
            ("M5", 5),
            ("M10", 10),
        ]
    )
    def test_newest_range_ends_exactly_at_nca(self, _name: str, m: int):
        ranges = rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=m)
        assert ranges[-1].end == self.NCA

    def test_total_lookback_matches_window_plus_m_minus_1_times_cadence(self):
        ranges = rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=3)
        oldest_start = ranges[0].start
        expected_lookback = dt.timedelta(minutes=15 + (3 - 1) * 5)
        assert self.NCA - oldest_start == expected_lookback

    @parameterized.expand(
        [
            ("M1_w15_c5", 1, 15, 5),
            ("M2_w15_c5", 2, 15, 5),
            ("M3_w15_c5", 3, 15, 5),
            ("M5_w30_c5", 5, 30, 5),
            ("M10_w60_c5", 10, 60, 5),
            ("M3_w5_c1", 3, 5, 1),
        ]
    )
    def test_each_range_is_exactly_window_minutes_wide(self, _name: str, m: int, window: int, cadence: int):
        ranges = rolling_check_ranges(self.NCA, window_minutes=window, cadence_minutes=cadence, period_count=m)
        for check_window in ranges:
            assert check_window.end - check_window.start == dt.timedelta(minutes=window)

    @parameterized.expand(
        [
            ("M2_w15_c5", 2, 15, 5),
            ("M3_w15_c5", 3, 15, 5),
            ("M5_w30_c5", 5, 30, 5),
        ]
    )
    def test_adjacent_ranges_offset_by_cadence(self, _name: str, m: int, window: int, cadence: int):
        ranges = rolling_check_ranges(self.NCA, window_minutes=window, cadence_minutes=cadence, period_count=m)
        for i in range(len(ranges) - 1):
            assert ranges[i + 1].start - ranges[i].start == dt.timedelta(minutes=cadence)
            assert ranges[i + 1].end - ranges[i].end == dt.timedelta(minutes=cadence)
