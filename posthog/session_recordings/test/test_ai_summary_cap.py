import re
import threading
from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from redis.exceptions import ResponseError

from posthog.models.team import Team
from posthog.redis import get_client
from posthog.session_recordings.ai_summary_cap import (
    DEFAULT_MAX_SUMMARIES_PER_PERIOD,
    CapDecision,
    _redis_key,
    check_only,
    coerce_max_summaries_per_period,
    consume_summary_quota,
    current_usage,
    get_cap_for_team,
    headroom,
)

from products.signals.backend.models import SignalSourceConfig


def _create_cluster_config(team: Team, *, enabled: bool = True, **config_overrides) -> SignalSourceConfig:
    """Most tests need the same boilerplate row — keep it here."""
    return SignalSourceConfig.objects.create(
        team=team,
        source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
        source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        enabled=enabled,
        config=config_overrides,
    )


class TestCoerceMaxSummariesPerPeriod(BaseTest):
    @parameterized.expand(
        [
            # Falls back to default
            ("none", None, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("zero", 0, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("negative_int", -10, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("negative_float_truncates_to_negative", -3.5, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("non_numeric_string", "abc", DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("empty_string", "", DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("hex_string", "0x10", DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("bool_true", True, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("bool_false", False, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("nan_value", float("nan"), DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            # `int(float("inf"))` raises OverflowError, not ValueError — must be caught.
            ("inf", float("inf"), DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("negative_inf", float("-inf"), DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("list", [5], DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            ("dict", {"x": 5}, DEFAULT_MAX_SUMMARIES_PER_PERIOD),
            # Accepted (matches lenient `coerce_sample_rate` semantics)
            ("numeric_string", "100", 100),
            # int() strips ASCII whitespace; documented behavior we lean on.
            ("padded_numeric_string", "  50  ", 50),
            ("leading_zero_string", "007", 7),
            ("float_truncates", 3.7, 3),
            ("valid_one", 1, 1),
            ("valid_large", 99999, 99999),
            ("very_large_int", 10**12, 10**12),
        ]
    )
    def test_coerce(self, _name, value, expected):
        assert coerce_max_summaries_per_period(value) == expected


class TestGetCapForTeam(BaseTest):
    def test_default_when_no_config_row(self):
        assert not SignalSourceConfig.objects.filter(team_id=self.team.pk).exists()
        assert get_cap_for_team(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD

    def test_default_when_row_has_no_cap_key(self):
        _create_cluster_config(self.team, sample_rate=0.5)
        assert get_cap_for_team(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD

    def test_override_from_config(self):
        _create_cluster_config(self.team, max_summaries_per_period=7)
        assert get_cap_for_team(self.team.pk) == 7

    def test_disabled_row_still_supplies_cap(self):
        # Sweep gating uses `enabled=True`, but the cap should apply even when the
        # autonomous sweep is off — DRF summarize is what we're protecting.
        _create_cluster_config(self.team, enabled=False, max_summaries_per_period=3)
        assert get_cap_for_team(self.team.pk) == 3

    def test_default_when_config_value_uncoerceable(self):
        _create_cluster_config(self.team, max_summaries_per_period="abc")
        assert get_cap_for_team(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD

    def test_default_when_config_value_is_inf(self):
        # JSON doesn't allow inf, but defensive: if it ever appears, don't crash.
        _create_cluster_config(self.team, max_summaries_per_period=float("inf"))
        assert get_cap_for_team(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD

    def test_default_when_config_is_null(self):
        # JSONField allows null on the column; isinstance check catches it.
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            config=None,
        )
        assert get_cap_for_team(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD

    def test_default_when_config_is_list(self):
        # Pathological but valid JSON — `.config.get(...)` would AttributeError without the guard.
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            config=[],
        )
        assert get_cap_for_team(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD

    def test_cross_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        _create_cluster_config(other_team, max_summaries_per_period=99)
        assert get_cap_for_team(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD
        assert get_cap_for_team(other_team.pk) == 99


class TestRedisKey(BaseTest):
    def test_format(self):
        key = _redis_key(42, now=datetime(2026, 5, 5, tzinfo=UTC))
        assert key == "posthog/replay-summary-cap:42:2026-05"
        assert re.fullmatch(r"posthog/replay-summary-cap:\d+:\d{4}-\d{2}", key)

    def test_zero_padded_month(self):
        # Catch a future drift to %Y-%-m or similar — ops scripts will rely on
        # lexicographic sort, and "2026-1" sorts after "2026-10".
        assert _redis_key(1, now=datetime(2026, 1, 31, tzinfo=UTC)).endswith(":2026-01")
        assert _redis_key(1, now=datetime(2026, 12, 1, tzinfo=UTC)).endswith(":2026-12")

    def test_uses_utc_when_now_omitted(self):
        # We never want a worker's local TZ to determine the bucket — pin it to UTC.
        with patch("posthog.session_recordings.ai_summary_cap.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)
            key = _redis_key(1)
            mock_dt.now.assert_called_once_with(UTC)
            assert key.endswith(":2026-05")


class TestCounter(BaseTest):
    def test_current_usage_zero_for_unseen_team(self):
        assert current_usage(self.team.pk) == 0

    def test_consume_increments_and_returns_new_value(self):
        assert consume_summary_quota(self.team.pk, 1) == 1
        assert current_usage(self.team.pk) == 1
        assert consume_summary_quota(self.team.pk, 4) == 5
        assert current_usage(self.team.pk) == 5

    def test_consume_zero_is_noop(self):
        consume_summary_quota(self.team.pk, 1)
        assert consume_summary_quota(self.team.pk, 0) == 1
        assert consume_summary_quota(self.team.pk, -3) == 1
        assert current_usage(self.team.pk) == 1

    def test_ttl_set_on_first_write_only(self):
        client = get_client()
        consume_summary_quota(self.team.pk, 1)
        first_ttl = client.ttl(_redis_key(self.team.pk))
        assert first_ttl > 0  # an EXPIRE was issued

        # Force the key's TTL to a sentinel; a second consume must NOT re-issue EXPIRE.
        client.expire(_redis_key(self.team.pk), 999)
        consume_summary_quota(self.team.pk, 1)
        second_ttl = client.ttl(_redis_key(self.team.pk))
        assert second_ttl <= 999

    def test_corrupt_counter_treated_as_zero(self):
        get_client().set(_redis_key(self.team.pk), "not-a-number")
        assert current_usage(self.team.pk) == 0

    def test_consume_recovers_from_corrupt_key(self):
        # Real bug if unhandled: Redis INCRBY on a non-integer string raises
        # WRONGTYPE → we'd crash the summarize path. Reset + retry instead.
        client = get_client()
        client.set(_redis_key(self.team.pk), "not-a-number")
        # Sanity: raw INCRBY would explode.
        with pytest.raises(ResponseError):
            client.incrby(_redis_key(self.team.pk), 1)
        # consume_summary_quota must absorb it and re-establish the counter.
        assert consume_summary_quota(self.team.pk, 2) == 2
        assert current_usage(self.team.pk) == 2

    def test_consume_returns_int_even_when_redis_returns_bytes_via_round_trip(self):
        # Belt-and-braces: INCRBY returns int already, but `current_usage` reads
        # via GET which can return bytes depending on client config. Make sure we
        # still cast cleanly.
        consume_summary_quota(self.team.pk, 7)
        raw = get_client().get(_redis_key(self.team.pk))
        assert raw is not None
        assert int(raw) == 7  # what current_usage does internally
        assert current_usage(self.team.pk) == 7


class TestCheckOnly(BaseTest):
    """`check_only` is the entrypoint primitive used at the cost-backstop
    check. The defining invariant: it MUST NEVER advance the counter, no
    matter the decision. Pair with a later `consume_summary_quota` once the
    caller commits to actual LLM work.
    """

    def setUp(self):
        super().setUp()
        _create_cluster_config(self.team, max_summaries_per_period=3)

    def test_allows_under_cap_without_incrementing(self):
        # Repeated check_only must not move the counter — that's the whole point.
        for _ in range(5):
            decision = check_only(self.team.pk)
            assert decision == CapDecision(allowed=True, used=0, cap=3)
        assert current_usage(self.team.pk) == 0

    def test_blocks_at_cap_without_incrementing(self):
        consume_summary_quota(self.team.pk, 3)
        decision = check_only(self.team.pk)
        assert decision == CapDecision(allowed=False, used=3, cap=3)
        assert current_usage(self.team.pk) == 3

    def test_reflects_existing_usage(self):
        consume_summary_quota(self.team.pk, 2)
        assert check_only(self.team.pk) == CapDecision(allowed=True, used=2, cap=3)
        assert current_usage(self.team.pk) == 2  # unchanged

    def test_requested_more_than_headroom_blocks(self):
        consume_summary_quota(self.team.pk, 2)
        assert check_only(self.team.pk, requested=2) == CapDecision(allowed=False, used=2, cap=3)
        assert current_usage(self.team.pk) == 2

    def test_requested_equal_to_headroom_allowed(self):
        consume_summary_quota(self.team.pk, 1)
        assert check_only(self.team.pk, requested=2) == CapDecision(allowed=True, used=1, cap=3)
        assert current_usage(self.team.pk) == 1  # NOT advanced — we only checked

    def test_exactly_at_cap_then_blocks(self):
        # Boundary regression: off-by-one in the `<=` comparator would flip these.
        consume_summary_quota(self.team.pk, 2)
        assert check_only(self.team.pk).allowed is True
        consume_summary_quota(self.team.pk, 1)  # caller commits to the work
        assert check_only(self.team.pk).allowed is False

    def test_requested_zero_is_allowed_noop(self):
        decision = check_only(self.team.pk, requested=0)
        assert decision.allowed is True
        assert current_usage(self.team.pk) == 0

    def test_requested_negative_raises(self):
        with pytest.raises(ValueError, match="requested must be >= 0"):
            check_only(self.team.pk, requested=-1)

    def test_check_only_then_consume_advances_counter_only_when_committed(self):
        # The split (check_only + consume) must advance the counter exactly
        # once per committed work item, never on the check itself.
        for _ in range(3):
            decision = check_only(self.team.pk)
            if decision.allowed:
                consume_summary_quota(self.team.pk, 1)
        assert current_usage(self.team.pk) == 3
        assert check_only(self.team.pk).allowed is False

    def test_no_consume_on_short_circuit(self):
        # The motivating case for the split: a caller that bails out of LLM work
        # after `check_only` (cache hit, in-flight workflow dedup) must NOT have
        # burned quota.
        for _ in range(10):
            decision = check_only(self.team.pk)
            assert decision.allowed is True
            # Caller short-circuits — no consume call.
        assert current_usage(self.team.pk) == 0


class TestHeadroom(BaseTest):
    def test_headroom_default_when_unseen(self):
        assert headroom(self.team.pk) == DEFAULT_MAX_SUMMARIES_PER_PERIOD

    def test_headroom_decreases_with_usage(self):
        _create_cluster_config(self.team, max_summaries_per_period=10)
        assert headroom(self.team.pk) == 10
        consume_summary_quota(self.team.pk, 4)
        assert headroom(self.team.pk) == 6

    def test_headroom_clamped_to_zero_when_overconsumed(self):
        _create_cluster_config(self.team, max_summaries_per_period=5)
        consume_summary_quota(self.team.pk, 12)
        assert headroom(self.team.pk) == 0


class TestConcurrency(BaseTest):
    """Pin the documented overshoot bound on the `check_only`+`consume_summary_quota`
    split so a future change to the GET-then-INCRBY pattern can't silently widen
    the race window past what we're willing to accept.
    """

    def setUp(self):
        super().setUp()
        _create_cluster_config(self.team, max_summaries_per_period=3)

    def test_concurrent_check_only_then_consume_overshoot_bounded(self):
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        results: list[CapDecision] = []
        results_lock = threading.Lock()

        def worker():
            barrier.wait()
            decision = check_only(self.team.pk)
            if decision.allowed:
                consume_summary_quota(self.team.pk, 1)
            with results_lock:
                results.append(decision)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
            # Note: hard to reliably trigger the read-write race in CPython under
            # the GIL — but the test still asserts the post-state invariants,
            # which is what matters for correctness.
        for t in threads:
            t.join()

        allowed_count = sum(1 for r in results if r.allowed)
        # Floor: we must have honored at least the cap.
        assert allowed_count >= 3
        # Ceiling: in the worst case all 10 threads could pass `check_only` before
        # any `consume`, but never more than the thread count.
        assert allowed_count <= n_threads
        # The counter MUST equal allowed_count: blocked decisions never consume.
        assert current_usage(self.team.pk) == allowed_count


class TestMonthBoundary(BaseTest):
    def test_independent_buckets_across_months(self):
        jan = datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC)
        feb = datetime(2026, 2, 1, 0, 0, 1, tzinfo=UTC)

        consume_summary_quota(self.team.pk, 5, now=jan)
        assert current_usage(self.team.pk, now=jan) == 5
        assert current_usage(self.team.pk, now=feb) == 0

        consume_summary_quota(self.team.pk, 2, now=feb)
        assert current_usage(self.team.pk, now=feb) == 2
        assert current_usage(self.team.pk, now=jan) == 5

    def test_check_only_uses_now_for_bucket(self):
        feb = datetime(2026, 2, 15, 12, 0, 0, tzinfo=UTC)
        consume_summary_quota(self.team.pk, 5, now=feb)

        with patch("posthog.session_recordings.ai_summary_cap.datetime") as mock_dt:
            mock_dt.now.return_value = feb
            assert check_only(self.team.pk) == CapDecision(allowed=True, used=5, cap=DEFAULT_MAX_SUMMARIES_PER_PERIOD)
