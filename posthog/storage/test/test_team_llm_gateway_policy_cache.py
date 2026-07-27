"""
Tests for the llm-gateway policy HyperCache.

Covers the projection shape the Go llm-gateway consumes, the null-default
behavior (no backfill required), and the signal-driven cache update path.
"""

import json
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.team.team import Team
from posthog.storage.team_llm_gateway_policy_cache import (
    LLM_GATEWAY_POLICY_FIELDS,
    _serialize_team_to_llm_gateway_policy,
    clear_team_llm_gateway_policy_cache,
    get_team_llm_gateway_policy,
    update_team_llm_gateway_policy_cache,
)
from posthog.tasks.team_llm_gateway_policy import update_team_llm_gateway_policy_cache_task


class TestLLMGatewayPolicyProjection(BaseTest):
    """The projection is the contract with the Go service — pin its shape."""

    def test_projection_has_expected_fields(self):
        # The field list must match what the serializer actually emits, so a
        # field added to one but not the other fails here.
        self.assertEqual(
            set(LLM_GATEWAY_POLICY_FIELDS),
            set(_serialize_team_to_llm_gateway_policy(self.team).keys()),
        )
        self.assertEqual(
            set(LLM_GATEWAY_POLICY_FIELDS),
            {"id", "api_token", "llm_gateway_enabled_at", "llm_gateway_revoked_at"},
        )

    def test_populated_team_round_trips_through_json(self):
        enabled_at = datetime(2026, 5, 29, 20, 46, 30, tzinfo=UTC)
        revoked_at = datetime(2026, 5, 20, 12, 34, 56, tzinfo=UTC)

        self.team.llm_gateway_enabled_at = enabled_at
        self.team.llm_gateway_revoked_at = revoked_at
        self.team.save()

        policy = _serialize_team_to_llm_gateway_policy(self.team)

        self.assertEqual(policy["id"], self.team.id)
        self.assertEqual(policy["api_token"], self.team.api_token)
        # Datetimes must be ISO8601 so the Go service can parse them from JSON.
        self.assertEqual(policy["llm_gateway_enabled_at"], enabled_at.isoformat())
        self.assertEqual(policy["llm_gateway_revoked_at"], revoked_at.isoformat())

        rehydrated = json.loads(json.dumps(policy))
        self.assertEqual(rehydrated, policy)

    def test_unset_team_serializes_to_null_enabled_and_revoked(self):
        """
        A team that has never been enrolled or revoked projects null for both,
        so the schema migration needs no backfill. The gateway reads null
        enabled_at as not enrolled (default-deny) and null revoked_at as not
        revoked.
        """
        policy = _serialize_team_to_llm_gateway_policy(self.team)

        self.assertEqual(policy["id"], self.team.id)
        self.assertEqual(policy["api_token"], self.team.api_token)
        self.assertIsNone(policy["llm_gateway_enabled_at"])
        self.assertIsNone(policy["llm_gateway_revoked_at"])


class TestLLMGatewayPolicyCacheOps(BaseTest):
    """Test the read/write/clear surface around the HyperCache."""

    @patch("posthog.storage.team_llm_gateway_policy_cache.team_llm_gateway_policy_hypercache")
    def test_get_and_update(self, mock_hypercache):
        mock_payload: dict[str, Any] = {
            "id": self.team.id,
            "api_token": self.team.api_token,
            "llm_gateway_enabled_at": None,
            "llm_gateway_revoked_at": None,
        }
        mock_hypercache.get_from_cache.return_value = mock_payload
        mock_hypercache.update_cache.return_value = True

        self.assertTrue(update_team_llm_gateway_policy_cache(self.team))

        policy = get_team_llm_gateway_policy(self.team)
        self.assertEqual(policy, mock_payload)

    @patch("posthog.storage.team_llm_gateway_policy_cache.team_llm_gateway_policy_hypercache")
    def test_clear(self, mock_hypercache):
        clear_team_llm_gateway_policy_cache(self.team, kinds=["redis"])
        mock_hypercache.clear_cache.assert_called_once_with(self.team, kinds=["redis"])


class TestLLMGatewayPolicyTasks(BaseTest):
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache")
    def test_update_task(self, mock_update):
        mock_update.return_value = True
        update_team_llm_gateway_policy_cache_task(self.team.id)
        self.assertEqual(mock_update.call_count, 1)
        self.assertEqual(mock_update.call_args[0][0].id, self.team.id)

    def test_update_task_missing_team_is_noop(self):
        update_team_llm_gateway_policy_cache_task(999999)


class TestLLMGatewayPolicySignals(BaseTest):
    """Verify the cache is invalidated independently of the team_metadata cache."""

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_team_save_enqueues_update(self, mock_delay, mock_settings, mock_transaction):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self.team.llm_gateway_revoked_at = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
        self.team.save()

        mock_delay.assert_called_with(self.team.id)

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_team_save_noop_without_ai_gateway_redis_url(self, mock_delay, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = None

        self.team.llm_gateway_revoked_at = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
        self.team.save()

        mock_delay.assert_not_called()

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.HYPERCACHE_SIGNAL_UPDATE_COUNTER")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_enqueue_failure_records_counter_and_does_not_propagate(
        self, mock_delay, mock_settings, mock_counter, mock_transaction
    ):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()
        mock_delay.side_effect = Exception("broker down")

        self.team.llm_gateway_revoked_at = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
        try:
            self.team.save()
        except Exception:
            self.fail("enqueue failure should not propagate to the caller")

        mock_counter.labels.assert_called_once_with(
            namespace="team_metadata", cache_name="llm_gateway_policy", operation="enqueue", result="failure"
        )
        mock_counter.labels.return_value.inc.assert_called_once_with()

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    def test_team_delete_clears_cache(self, mock_clear, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True

        team = Team.objects.create(organization=self.organization, name="Doomed")
        team.delete()

        mock_clear.assert_called_once()

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_api_token_rotation_clears_old_token_cache(self, mock_delay, mock_clear, mock_settings, mock_transaction):
        """
        Rotating api_token must invalidate the cache keyed by the OLD token.
        Otherwise a holder of the rotated token keeps hitting the gateway via
        the stale cached policy until the 7-day TTL expires.
        """
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        old_token = self.team.api_token
        self.team.api_token = "phc_rotated_token_value"
        self.team.save()

        mock_delay.assert_called_with(self.team.id)
        mock_clear.assert_called_once_with(old_token, kinds=["redis"])

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_unrelated_save_does_not_clear_cache(self, mock_delay, mock_clear, mock_settings, mock_transaction):
        """A save that touches no tracked field (api_token, llm_gateway_enabled_at,
        llm_gateway_revoked_at) must not invalidate the cache; the async task still
        refreshes the blob."""
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self.team.name = "Renamed"
        self.team.save()

        mock_delay.assert_called_with(self.team.id)
        mock_clear.assert_not_called()

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_setting_revoked_at_clears_current_token_cache_on_commit(
        self, mock_delay, mock_clear, mock_settings, mock_transaction
    ):
        """
        Setting llm_gateway_revoked_at must invalidate the current token's
        cache entry synchronously on commit. The async refresh task can lag,
        so without a synchronous clear, the stale active policy stays usable
        for the full cache TTL and a holder of the token keeps hitting the
        gateway as if the team were active.
        """
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self.team.llm_gateway_revoked_at = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
        self.team.save()

        mock_delay.assert_called_with(self.team.id)
        mock_clear.assert_called_once_with(self.team, kinds=["redis"])

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_setting_enabled_at_clears_current_token_cache_on_commit(
        self, mock_delay, mock_clear, mock_settings, mock_transaction
    ):
        """
        Setting llm_gateway_enabled_at must invalidate synchronously for the
        same reason as the revoke path: until the async task runs, the
        gateway would keep treating the team as not-enrolled and 401 every
        request even after admin flips them on.
        """
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self.team.llm_gateway_enabled_at = datetime(2026, 5, 29, 20, 46, 30, tzinfo=UTC)
        self.team.save()

        mock_delay.assert_called_with(self.team.id)
        mock_clear.assert_called_once_with(self.team, kinds=["redis"])

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_chained_token_rotation_clears_each_old_token(
        self, mock_delay, mock_clear, mock_settings, mock_transaction
    ):
        """
        Two rotations on the same kept-alive instance (A->B->C) must clear A then
        B. post_save re-snapshots the saved token so the second save compares
        against B, instead of clearing A twice and leaking B for the full cache TTL.
        """
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        token_a = self.team.api_token

        self.team.api_token = "phc_rotated_b"
        self.team.save()

        self.team.api_token = "phc_rotated_c"
        self.team.save()

        cleared = [call.args[0] for call in mock_clear.call_args_list]
        self.assertEqual(cleared, [token_a, "phc_rotated_b"])

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_deferred_api_token_load_still_clears_old_token_on_rotation(
        self, mock_delay, mock_clear, mock_settings, mock_transaction
    ):
        """
        A Team fetched with api_token deferred (.only() / .defer()) and then
        rotated must still clear the old token's cache entry. post_init skips the
        snapshot to avoid a lazy load; the pre_save fallback captures the old
        value from the DB before the UPDATE runs.
        """
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        old_token = self.team.api_token
        partial = Team.objects.only("id", "name").get(pk=self.team.pk)
        partial.api_token = "phc_rotated_deferred"
        partial.save()

        mock_delay.assert_called_with(self.team.id)
        mock_clear.assert_called_once_with(old_token, kinds=["redis"])

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_simultaneous_enable_and_revoke_clears_cache_once(
        self, mock_delay, mock_clear, mock_settings, mock_transaction
    ):
        """
        Flipping both llm_gateway_enabled_at and llm_gateway_revoked_at in one
        save must invalidate exactly once. The handler ORs the two change
        signals; a future refactor that fires clear per field would double the
        Redis traffic on every admin enable-after-revoke.
        """
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self.team.llm_gateway_enabled_at = datetime(2026, 5, 29, 20, 46, 30, tzinfo=UTC)
        self.team.llm_gateway_revoked_at = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)
        self.team.save()

        mock_delay.assert_called_with(self.team.id)
        mock_clear.assert_called_once_with(self.team, kinds=["redis"])

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_deferred_enabled_at_load_still_clears_cache_on_flip(
        self, mock_delay, mock_clear, mock_settings, mock_transaction
    ):
        """
        A Team fetched with llm_gateway_enabled_at deferred and then flipped
        on must still invalidate the cache. post_init skips the snapshot to
        avoid a lazy load; the pre_save fallback captures the old value from
        the DB before the UPDATE runs.
        """
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        partial = Team.objects.only("id", "name").get(pk=self.team.pk)
        partial.llm_gateway_enabled_at = datetime(2026, 5, 29, 20, 46, 30, tzinfo=UTC)
        partial.save()

        mock_delay.assert_called_with(self.team.id)
        mock_clear.assert_called_once_with(partial, kinds=["redis"])

    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.team_llm_gateway_policy_signal_handlers.clear_team_llm_gateway_policy_cache")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_chained_enabled_at_flips_invalidate_each_save(
        self, mock_delay, mock_clear, mock_settings, mock_transaction
    ):
        """
        Two consecutive enabled_at writes on the same kept-alive instance must
        invalidate twice. post_save re-snapshots the saved value so the second
        save compares against t1 instead of seeing "unchanged" and skipping.
        """
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self.team.llm_gateway_enabled_at = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)
        self.team.save()

        self.team.llm_gateway_enabled_at = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)
        self.team.save()

        self.assertEqual(mock_clear.call_count, 2)
