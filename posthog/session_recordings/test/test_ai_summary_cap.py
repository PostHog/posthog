from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.redis import get_client
from posthog.session_recordings.ai_summary_cap import (
    DEFAULT_MAX_SUMMARIES_PER_PERIOD,
    CapDecision,
    _redis_key,
    check_and_consume,
    coerce_max_summaries_per_period,
    consume,
    current_usage,
    get_cap_for_team,
)

from products.signals.backend.models import SignalSourceConfig


class TestCoerceMaxSummariesPerPeriod(BaseTest):
    @parameterized.expand(
        [
            ("none", None, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("zero", 0, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("negative", -10, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("non_numeric_string", "abc", DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("bool_true", True, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("bool_false", False, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("nan_value", float("nan"), DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            # Numeric strings round-trip through int(), matching the lenient
            # semantics of `coerce_sample_rate`.
            ("numeric_string", "100", 100),
            ("float_truncates", 3.7, 3),
            ("valid_one", 1, 1),
            ("valid_large", 99999, 99999),
        ]
    )
    def test_coerce(self, _name, value, expected):
        assert coerce_max_summaries_per_period(value) == expected


class TestGetCapForTeam(BaseTest):
    def test_default_when_no_config_row(self):
        # Sanity: team has no SignalSourceConfig row at all
        assert not SignalSourceConfig.objects.filter(team_id=self.team.pk).exists()
        assert get_cap_for_team(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD

    def test_default_when_row_has_no_cap_key(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            config={"sample_rate": 0.5},
        )
        assert get_cap_for_team(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD

    def test_override_from_config(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            config={"max_summaries_per_period": 7},
        )
        assert get_cap_for_team(self.team.pk) == 7

    def test_disabled_row_still_supplies_cap(self):
        # Sweep gating uses `enabled=True`, but the cap should apply even when the
        # autonomous sweep is off — DRF summarize is what we're protecting.
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            enabled=False,
            config={"max_summaries_per_period": 3},
        )
        assert get_cap_for_team(self.team.pk) == 3


class TestCounter(BaseTest):
    def test_current_usage_zero_for_unseen_team(self):
        assert current_usage(self.team.pk) == 0

    def test_consume_increments_and_returns_new_value(self):
        assert consume(self.team.pk, 1) == 1
        assert current_usage(self.team.pk) == 1
        assert consume(self.team.pk, 4) == 5
        assert current_usage(self.team.pk) == 5

    def test_consume_zero_is_noop(self):
        consume(self.team.pk, 1)
        assert consume(self.team.pk, 0) == 1
        assert consume(self.team.pk, -3) == 1
        assert current_usage(self.team.pk) == 1

    def test_ttl_set_on_first_write_only(self):
        client = get_client()
        # Pre-touch the key to a TTL we can detect — proxy for "TTL was set on first INCRBY".
        consume(self.team.pk, 1)
        first_ttl = client.ttl(_redis_key(self.team.pk))
        assert first_ttl > 0  # an EXPIRE was issued

        # Force the key's TTL to a sentinel; a second consume must NOT re-issue EXPIRE.
        client.expire(_redis_key(self.team.pk), 999)
        consume(self.team.pk, 1)
        second_ttl = client.ttl(_redis_key(self.team.pk))
        assert second_ttl <= 999  # not re-set by consume; still counting down from 999

    def test_corrupt_counter_treated_as_zero(self):
        get_client().set(_redis_key(self.team.pk), "not-a-number")
        assert current_usage(self.team.pk) == 0


class TestCheckAndConsume(BaseTest):
    def setUp(self):
        super().setUp()
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            config={"max_summaries_per_period": 3},
        )

    def test_allows_under_cap_and_increments(self):
        assert check_and_consume(self.team.pk) == CapDecision(allowed=True, used=1, cap=3)
        assert check_and_consume(self.team.pk) == CapDecision(allowed=True, used=2, cap=3)
        assert check_and_consume(self.team.pk) == CapDecision(allowed=True, used=3, cap=3)

    def test_blocks_at_cap_without_incrementing(self):
        consume(self.team.pk, 3)
        decision = check_and_consume(self.team.pk)
        assert decision == CapDecision(allowed=False, used=3, cap=3)
        # Counter not advanced when blocked
        assert current_usage(self.team.pk) == 3

    def test_requested_more_than_headroom_blocks(self):
        consume(self.team.pk, 2)
        decision = check_and_consume(self.team.pk, requested=2)
        assert decision == CapDecision(allowed=False, used=2, cap=3)
        assert current_usage(self.team.pk) == 2

    def test_requested_equal_to_headroom_allowed(self):
        consume(self.team.pk, 1)
        decision = check_and_consume(self.team.pk, requested=2)
        assert decision == CapDecision(allowed=True, used=3, cap=3)


class TestMonthBoundary(BaseTest):
    def test_independent_buckets_across_months(self):
        jan = datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC)
        feb = datetime(2026, 2, 1, 0, 0, 1, tzinfo=UTC)

        consume(self.team.pk, 5, now=jan)
        assert current_usage(self.team.pk, now=jan) == 5
        # New month starts fresh
        assert current_usage(self.team.pk, now=feb) == 0

        consume(self.team.pk, 2, now=feb)
        assert current_usage(self.team.pk, now=feb) == 2
        # January bucket untouched
        assert current_usage(self.team.pk, now=jan) == 5

    def test_check_and_consume_uses_now_for_bucket(self):
        feb = datetime(2026, 2, 15, 12, 0, 0, tzinfo=UTC)

        with patch("posthog.session_recordings.ai_summary_cap.datetime") as mock_dt:
            mock_dt.now.return_value = feb
            # Default cap (no SignalSourceConfig row), make sure we land in the feb bucket
            assert check_and_consume(self.team.pk) == CapDecision(
                allowed=True, used=1, cap=DEFAULT_MAX_SUMMARIES_PER_PERIOD
            )
        assert current_usage(self.team.pk, now=feb) == 1
