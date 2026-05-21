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
        self.assertEqual(
            set(LLM_GATEWAY_POLICY_FIELDS),
            {
                "id",
                "api_token",
                "llm_gateway_allowed_models",
                "llm_gateway_tier",
                "llm_gateway_revoked_at",
            },
        )

    def test_populated_team_round_trips_through_json(self):
        revoked_at = datetime(2026, 5, 20, 12, 34, 56, tzinfo=UTC)

        self.team.llm_gateway_allowed_models = [
            "openai/gpt-4o",
            "anthropic/claude-sonnet-4-6",
        ]
        self.team.llm_gateway_tier = "enterprise"
        self.team.llm_gateway_revoked_at = revoked_at
        self.team.save()

        policy = _serialize_team_to_llm_gateway_policy(self.team)

        self.assertEqual(policy["id"], self.team.id)
        self.assertEqual(policy["api_token"], self.team.api_token)
        self.assertEqual(
            policy["llm_gateway_allowed_models"],
            ["openai/gpt-4o", "anthropic/claude-sonnet-4-6"],
        )
        self.assertEqual(policy["llm_gateway_tier"], "enterprise")
        # Datetime must be ISO8601 so the Go service can parse it from JSON.
        self.assertEqual(policy["llm_gateway_revoked_at"], revoked_at.isoformat())

        rehydrated = json.loads(json.dumps(policy))
        self.assertEqual(rehydrated, policy)

    def test_unset_team_serializes_to_nulls(self):
        """
        A team with no llm_gateway_* overrides projects nulls, not defaults.
        The Go service is responsible for normalizing null -> ("free", [], not
        revoked); this keeps the schema migration backfill-free.
        """
        policy = _serialize_team_to_llm_gateway_policy(self.team)

        self.assertEqual(policy["id"], self.team.id)
        self.assertEqual(policy["api_token"], self.team.api_token)
        self.assertIsNone(policy["llm_gateway_allowed_models"])
        self.assertIsNone(policy["llm_gateway_tier"])
        self.assertIsNone(policy["llm_gateway_revoked_at"])


class TestLLMGatewayPolicyCacheOps(BaseTest):
    """Test the read/write/clear surface around the HyperCache."""

    @patch("posthog.storage.team_llm_gateway_policy_cache.team_llm_gateway_policy_hypercache")
    def test_get_and_update(self, mock_hypercache):
        mock_payload: dict[str, Any] = {
            "id": self.team.id,
            "api_token": self.team.api_token,
            "llm_gateway_allowed_models": None,
            "llm_gateway_tier": None,
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

    @patch("posthog.tasks.team_llm_gateway_policy.transaction")
    @patch("posthog.tasks.team_llm_gateway_policy.settings")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_team_save_enqueues_update(self, mock_delay, mock_settings, mock_transaction):
        mock_settings.FLAGS_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self.team.llm_gateway_tier = "pro"
        self.team.save()

        mock_delay.assert_called_with(self.team.id)

    @patch("posthog.tasks.team_llm_gateway_policy.settings")
    @patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay")
    def test_team_save_noop_without_flags_redis_url(self, mock_delay, mock_settings):
        mock_settings.FLAGS_REDIS_URL = None

        self.team.llm_gateway_tier = "pro"
        self.team.save()

        mock_delay.assert_not_called()

    @patch("posthog.tasks.team_llm_gateway_policy.settings")
    @patch("posthog.tasks.team_llm_gateway_policy.clear_team_llm_gateway_policy_cache")
    def test_team_delete_clears_cache(self, mock_clear, mock_settings):
        mock_settings.FLAGS_REDIS_URL = "redis://localhost"
        mock_settings.TEST = True

        team = Team.objects.create(organization=self.organization, name="Doomed")
        team.delete()

        mock_clear.assert_called_once()
