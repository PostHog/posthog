import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction

from parameterized import parameterized
from redis.exceptions import ConnectionError as RedisConnectionError

from posthog.models import Team
from posthog.redis import TEST_clear_clients
from posthog.token_bucket import TEST_reset_scripts

from products.cloud_agents.backend.facade.contracts import ConcurrencyLimited, CreateRateLimited
from products.cloud_agents.backend.logic import limits
from products.cloud_agents.backend.models import TeamCloudAgentsConfig


class TestConcurrencyGuard(BaseTest):
    @parameterized.expand(
        [
            # name, override, active runs, raises
            ("below_default", None, 4, False),
            ("at_default", None, 5, True),
            ("above_default", None, 9, True),
            ("override_raises_limit", 20, 5, False),
            ("at_override", 20, 20, True),
            ("override_lowers_limit", 1, 1, True),
            ("zero_override_blocks_all", 0, 0, True),
        ]
    )
    def test_limit(self, _name: str, override: int | None, active: int, raises: bool) -> None:
        if override is not None:
            TeamCloudAgentsConfig.objects.create(team=self.team, max_concurrent_runs=override)
        expected_limit = limits.DEFAULT_MAX_CONCURRENT_RUNS if override is None else override

        with transaction.atomic():
            if raises:
                with self.assertRaises(ConcurrencyLimited) as raised:
                    limits.concurrency_guard(self.team.id, lambda: active)
                assert (raised.exception.limit, raised.exception.active) == (expected_limit, active)
            else:
                limits.concurrency_guard(self.team.id, lambda: active)

    def test_override_of_another_team_does_not_apply(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        TeamCloudAgentsConfig.all_teams.create(team=other_team, max_concurrent_runs=100)
        with transaction.atomic(), self.assertRaises(ConcurrencyLimited):
            limits.concurrency_guard(self.team.id, lambda: limits.DEFAULT_MAX_CONCURRENT_RUNS)


class TestCreateRate(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        TEST_reset_scripts()
        self.addCleanup(TEST_clear_clients)
        self.addCleanup(TEST_reset_scripts)

    def test_burst_then_limited_with_retry_after_then_refill(self) -> None:
        with time_machine.travel("2026-01-01 00:00:00", tick=False) as frozen:
            for _ in range(limits.CREATE_RATE_BURST):
                limits.consume_create_rate(self.team.id)
            with self.assertRaises(CreateRateLimited) as raised:
                limits.consume_create_rate(self.team.id)
            # 60 per hour is one token per minute.
            assert raised.exception.retry_after == 60

            frozen.shift(60)
            limits.consume_create_rate(self.team.id)

    def test_refund_gives_the_token_back(self) -> None:
        with time_machine.travel("2026-01-01 00:00:00", tick=False):
            for _ in range(limits.CREATE_RATE_BURST):
                limits.consume_create_rate(self.team.id)
            limits.refund_create_rate(self.team.id)
            limits.consume_create_rate(self.team.id)
            with self.assertRaises(CreateRateLimited):
                limits.consume_create_rate(self.team.id)

    def test_teams_have_separate_buckets(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        with time_machine.travel("2026-01-01 00:00:00", tick=False):
            for _ in range(limits.CREATE_RATE_BURST):
                limits.consume_create_rate(self.team.id)
            limits.consume_create_rate(other_team.id)

    def test_override_changes_the_rate(self) -> None:
        TeamCloudAgentsConfig.objects.create(team=self.team, create_rate_per_hour=3600)
        with time_machine.travel("2026-01-01 00:00:00", tick=False):
            for _ in range(limits.CREATE_RATE_BURST):
                limits.consume_create_rate(self.team.id)
            with self.assertRaises(CreateRateLimited) as raised:
                limits.consume_create_rate(self.team.id)
            assert raised.exception.retry_after == 1

    def test_fails_open_when_redis_is_unavailable(self) -> None:
        before = limits.CREATE_RATE_UNAVAILABLE_COUNTER._value.get()
        with patch("posthog.token_bucket._scripts") as scripts:
            scripts.return_value.consume.side_effect = RedisConnectionError("down")
            for _ in range(limits.CREATE_RATE_BURST + 5):
                limits.consume_create_rate(self.team.id)
        assert limits.CREATE_RATE_UNAVAILABLE_COUNTER._value.get() == before + limits.CREATE_RATE_BURST + 5
