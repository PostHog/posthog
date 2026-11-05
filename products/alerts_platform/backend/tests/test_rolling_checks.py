import datetime as dt
from datetime import UTC, datetime

import unittest

from hypothesis import (
    given,
    settings,
    strategies as st,
)

from products.alerts_platform.backend.facade.rolling_checks import (
    CHECKPOINT_MAX_STALENESS,
    derive_breaches,
    resolve_alert_date_to,
)


class TestResolveAlertDateTo(unittest.TestCase):
    NEXT_CHECK_AT = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_none_checkpoint_returns_next_check_at(self):
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, None) == self.NEXT_CHECK_AT

    def test_fresh_checkpoint_in_past_is_used(self):
        checkpoint = self.NEXT_CHECK_AT - dt.timedelta(seconds=30)
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, checkpoint) == checkpoint

    def test_checkpoint_equal_to_next_check_at_is_used(self):
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, self.NEXT_CHECK_AT) == self.NEXT_CHECK_AT

    def test_future_checkpoint_is_clamped_to_next_check_at(self):
        checkpoint = self.NEXT_CHECK_AT + dt.timedelta(seconds=60)
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, checkpoint) == self.NEXT_CHECK_AT

    def test_stale_checkpoint_beyond_threshold_falls_back_to_next_check_at(self):
        # The "quiet partition pins min() backwards" case — must not strand spikes
        # on active partitions in the past.
        checkpoint = self.NEXT_CHECK_AT - CHECKPOINT_MAX_STALENESS - dt.timedelta(seconds=1)
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, checkpoint) == self.NEXT_CHECK_AT

    def test_checkpoint_exactly_at_threshold_is_still_used(self):
        checkpoint = self.NEXT_CHECK_AT - CHECKPOINT_MAX_STALENESS
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, checkpoint) == checkpoint


class TestDeriveBreachesProperties(unittest.TestCase):
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
