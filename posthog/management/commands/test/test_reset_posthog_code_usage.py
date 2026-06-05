from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

import fakeredis

from posthog.management.commands.reset_posthog_code_usage import (
    _product_patterns,
    _request_patterns,
    _user_cost_patterns,
    reset_keys,
)

BURST = "ratelimit:cost:user:user_cost_burst:posthog_code"
SUSTAINED = "ratelimit:cost:user:user_cost_sustained:posthog_code"
PRODUCT = "ratelimit:cost:product:posthog_code"
REQ_BURST = "ratelimit:burst"
REQ_SUSTAINED = "ratelimit:sustained"


@override_settings(LLM_GATEWAY_REDIS_URL="redis://localhost:6379")
class TestResetPostHogCodeUsage(SimpleTestCase):
    def setUp(self):
        self.client = fakeredis.FakeRedis()
        patcher = patch("posthog.management.commands.reset_posthog_code_usage.redis.from_url", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _seed(self, *keys: str) -> None:
        for key in keys:
            self.client.set(key, "1.0")

    def _exists(self, key: str) -> bool:
        return bool(self.client.exists(key))

    def test_reset_single_user_clears_only_that_user(self):
        self._seed(
            f"{BURST}:100",
            f"{SUSTAINED}:100:period:3",
            f"{SUSTAINED}:100:tm5:period:3",
            f"{REQ_BURST}:100",
            f"{REQ_SUSTAINED}:100",
            f"{BURST}:200",
            f"{REQ_BURST}:200",
        )

        call_command("reset_posthog_code_usage", "--user-id", "100")

        self.assertFalse(self._exists(f"{BURST}:100"))
        self.assertFalse(self._exists(f"{SUSTAINED}:100:period:3"))
        self.assertFalse(self._exists(f"{SUSTAINED}:100:tm5:period:3"))
        # Request-rate counters for the user are cleared too.
        self.assertFalse(self._exists(f"{REQ_BURST}:100"))
        self.assertFalse(self._exists(f"{REQ_SUSTAINED}:100"))
        # Another user is untouched.
        self.assertTrue(self._exists(f"{BURST}:200"))
        self.assertTrue(self._exists(f"{REQ_BURST}:200"))

    def test_trailing_colon_prevents_prefix_collision(self):
        # User "100" must not match user "1000".
        self._seed(f"{BURST}:100", f"{BURST}:1000", f"{REQ_BURST}:100", f"{REQ_BURST}:1000")

        call_command("reset_posthog_code_usage", "--user-id", "100")

        self.assertFalse(self._exists(f"{BURST}:100"))
        self.assertTrue(self._exists(f"{BURST}:1000"))
        # Request-rate keys are matched exactly, so "100" never touches "1000".
        self.assertFalse(self._exists(f"{REQ_BURST}:100"))
        self.assertTrue(self._exists(f"{REQ_BURST}:1000"))

    def test_glob_metachars_are_escaped(self):
        # A user_id of "10*" must not expand to wipe "100"/"101".
        self._seed(f"{BURST}:100", f"{BURST}:101", f"{BURST}:10*")

        call_command("reset_posthog_code_usage", "--user-id", "10*")

        self.assertFalse(self._exists(f"{BURST}:10*"))
        self.assertTrue(self._exists(f"{BURST}:100"))
        self.assertTrue(self._exists(f"{BURST}:101"))

    def test_all_users_clears_every_user(self):
        self._seed(
            f"{BURST}:100",
            f"{SUSTAINED}:200:period:1",
            f"{REQ_BURST}:100",
            f"{REQ_SUSTAINED}:200",
            f"{PRODUCT}",
        )

        call_command("reset_posthog_code_usage", "--all-users")

        self.assertFalse(self._exists(f"{BURST}:100"))
        self.assertFalse(self._exists(f"{SUSTAINED}:200:period:1"))
        self.assertFalse(self._exists(f"{REQ_BURST}:100"))
        self.assertFalse(self._exists(f"{REQ_SUSTAINED}:200"))
        # Product-wide pool is untouched unless --product-total is passed.
        self.assertTrue(self._exists(f"{PRODUCT}"))

    def test_cost_only_leaves_request_rate(self):
        self._seed(f"{BURST}:100", f"{REQ_BURST}:100", f"{REQ_SUSTAINED}:100")

        call_command("reset_posthog_code_usage", "--user-id", "100", "--cost")

        self.assertFalse(self._exists(f"{BURST}:100"))
        self.assertTrue(self._exists(f"{REQ_BURST}:100"))
        self.assertTrue(self._exists(f"{REQ_SUSTAINED}:100"))

    def test_request_only_leaves_cost(self):
        self._seed(f"{BURST}:100", f"{SUSTAINED}:100:period:1", f"{REQ_BURST}:100", f"{REQ_SUSTAINED}:100")

        call_command("reset_posthog_code_usage", "--user-id", "100", "--request")

        self.assertTrue(self._exists(f"{BURST}:100"))
        self.assertTrue(self._exists(f"{SUSTAINED}:100:period:1"))
        self.assertFalse(self._exists(f"{REQ_BURST}:100"))
        self.assertFalse(self._exists(f"{REQ_SUSTAINED}:100"))

    def test_cost_and_request_together_reset_both(self):
        self._seed(f"{BURST}:100", f"{REQ_BURST}:100")

        call_command("reset_posthog_code_usage", "--user-id", "100", "--cost", "--request")

        self.assertFalse(self._exists(f"{BURST}:100"))
        self.assertFalse(self._exists(f"{REQ_BURST}:100"))

    def test_request_rate_glob_does_not_match_cost_keys(self):
        # The "ratelimit:burst:*" / "ratelimit:sustained:*" globs must not sweep
        # up the "ratelimit:cost:..." counters.
        self._seed(f"{REQ_BURST}:100", f"{REQ_SUSTAINED}:100", f"{BURST}:100", f"{SUSTAINED}:100:period:1")

        deleted = reset_keys(self.client, _request_patterns(None), dry_run=False)

        self.assertEqual(deleted, 2)
        self.assertFalse(self._exists(f"{REQ_BURST}:100"))
        self.assertFalse(self._exists(f"{REQ_SUSTAINED}:100"))
        self.assertTrue(self._exists(f"{BURST}:100"))
        self.assertTrue(self._exists(f"{SUSTAINED}:100:period:1"))

    def test_product_total_clears_aggregate_pool(self):
        self._seed(f"{PRODUCT}", f"{PRODUCT}:tm5", f"{BURST}:100")

        call_command("reset_posthog_code_usage", "--product-total")

        self.assertFalse(self._exists(f"{PRODUCT}"))
        self.assertFalse(self._exists(f"{PRODUCT}:tm5"))
        # Per-user counters are untouched unless a user flag is passed.
        self.assertTrue(self._exists(f"{BURST}:100"))

    def test_dry_run_deletes_nothing(self):
        self._seed(f"{BURST}:100", f"{SUSTAINED}:100:period:1")

        call_command("reset_posthog_code_usage", "--user-id", "100", "--dry-run")

        self.assertTrue(self._exists(f"{BURST}:100"))
        self.assertTrue(self._exists(f"{SUSTAINED}:100:period:1"))

    def test_requires_a_target(self):
        with self.assertRaises(CommandError):
            call_command("reset_posthog_code_usage")

    def test_user_id_and_all_users_are_mutually_exclusive(self):
        with self.assertRaises(CommandError):
            call_command("reset_posthog_code_usage", "--user-id", "100", "--all-users")

    @override_settings(LLM_GATEWAY_REDIS_URL=None)
    def test_errors_when_redis_not_configured(self):
        with self.assertRaises(CommandError):
            call_command("reset_posthog_code_usage", "--all-users")

    @override_settings(LLM_GATEWAY_REDIS_URL=None)
    def test_redis_url_override_is_used_when_setting_absent(self):
        self._seed(f"{BURST}:100")

        call_command("reset_posthog_code_usage", "--user-id", "100", "--redis-url", "redis://override:6379")

        self.assertFalse(self._exists(f"{BURST}:100"))

    def test_reset_keys_counts_affected(self):
        self._seed(f"{BURST}:100", f"{SUSTAINED}:100:period:1")

        affected = reset_keys(self.client, _user_cost_patterns("100"), dry_run=False)

        self.assertEqual(affected, 2)

    def test_patterns_helpers(self):
        self.assertEqual(
            _user_cost_patterns(None),
            (f"{BURST}:*", f"{SUSTAINED}:*"),
        )
        self.assertEqual(_product_patterns(), (PRODUCT, f"{PRODUCT}:tm*"))
        self.assertEqual(_request_patterns(None), (f"{REQ_BURST}:*", f"{REQ_SUSTAINED}:*"))
        self.assertEqual(_request_patterns("100"), (f"{REQ_BURST}:100", f"{REQ_SUSTAINED}:100"))
