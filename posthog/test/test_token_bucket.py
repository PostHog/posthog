from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from redis.exceptions import ConnectionError as RedisConnectionError

from posthog.redis import TEST_clear_clients
from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, TEST_reset_scripts, consume, peek, refund

# 1 token per second, so refill math reads directly in seconds.
ONE_PER_SECOND = Budget(burst=10, per_hour=3600)


class TestTokenBucket(SimpleTestCase):
    def setUp(self) -> None:
        TEST_clear_clients()
        TEST_reset_scripts()
        self.addCleanup(TEST_clear_clients)
        self.addCleanup(TEST_reset_scripts)

    def test_burst_then_deny_with_accurate_retry_after(self) -> None:
        with freeze_time("2026-01-01 00:00:00"):
            for _ in range(ONE_PER_SECOND.burst):
                decision = consume("bucket:burst", ONE_PER_SECOND)
                assert isinstance(decision, BucketDecision)
                assert decision.allowed

            denied = consume("bucket:burst", ONE_PER_SECOND)
            assert isinstance(denied, BucketDecision)
            assert not denied.allowed
            assert denied.remaining == 0
            assert denied.retry_after == 1
            assert denied.reset == ONE_PER_SECOND.burst

    def test_continuous_refill_and_burst_cap(self) -> None:
        with freeze_time("2026-01-01 00:00:00") as frozen:
            for _ in range(ONE_PER_SECOND.burst):
                consume("bucket:refill", ONE_PER_SECOND)

            frozen.tick(5)
            decision = consume("bucket:refill", ONE_PER_SECOND)
            assert isinstance(decision, BucketDecision)
            assert decision.allowed
            assert decision.remaining == 4

            # A long idle refills to capacity, never beyond it.
            frozen.tick(100_000)
            decision = consume("bucket:refill", ONE_PER_SECOND)
            assert isinstance(decision, BucketDecision)
            assert decision.remaining == ONE_PER_SECOND.burst - 1

    def test_refund_returns_tokens_capped_at_capacity(self) -> None:
        with freeze_time("2026-01-01 00:00:00"):
            for _ in range(3):
                consume("bucket:refund", ONE_PER_SECOND)
            assert refund("bucket:refund", ONE_PER_SECOND) == 8
            assert refund("bucket:refund", ONE_PER_SECOND, cost=100) == ONE_PER_SECOND.burst
            # A missing key is a full bucket; nothing to give back.
            assert refund("bucket:never-charged", ONE_PER_SECOND) == ONE_PER_SECOND.burst

    def test_peek_reads_without_charging(self) -> None:
        with freeze_time("2026-01-01 00:00:00"):
            fresh = peek("bucket:peek", ONE_PER_SECOND)
            assert isinstance(fresh, BucketDecision)
            assert fresh.allowed
            assert fresh.remaining == ONE_PER_SECOND.burst

            consume("bucket:peek", ONE_PER_SECOND)
            first, second = (peek("bucket:peek", ONE_PER_SECOND) for _ in range(2))
            assert isinstance(first, BucketDecision) and isinstance(second, BucketDecision)
            assert first.remaining == second.remaining == ONE_PER_SECOND.burst - 1

    def test_redis_error_returns_unavailable_instead_of_raising(self) -> None:
        broken = MagicMock()
        broken.register_script.return_value.side_effect = RedisConnectionError("down")
        broken.hmget.side_effect = RedisConnectionError("down")
        TEST_reset_scripts()
        with patch("posthog.token_bucket.get_client", return_value=broken):
            assert isinstance(consume("bucket:down", ONE_PER_SECOND), BucketUnavailable)
            assert isinstance(refund("bucket:down", ONE_PER_SECOND), BucketUnavailable)
            assert isinstance(peek("bucket:down", ONE_PER_SECOND), BucketUnavailable)
        TEST_reset_scripts()

    @parameterized.expand(
        [
            ("zero_cost", 0),
            ("cost_above_burst", 11),
        ]
    )
    def test_invalid_cost_is_a_programmer_error(self, _name: str, cost: int) -> None:
        with self.assertRaises(ValueError):
            consume("bucket:invalid", ONE_PER_SECOND, cost=cost)

    @parameterized.expand(
        [
            ("zero_burst", 0, 60),
            ("zero_rate", 10, 0),
        ]
    )
    def test_invalid_budget_is_a_programmer_error(self, _name: str, burst: int, per_hour: int) -> None:
        with self.assertRaises(ValueError):
            Budget(burst=burst, per_hour=per_hour)
