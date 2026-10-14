import json
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

from posthog.models.team.team import Team
from posthog.storage.team_llm_gateway_account_trust_cache import (
    refresh_account_trust_caches,
    team_llm_gateway_account_trust_hypercache as hypercache,
    update_team_account_trust,
)
from posthog.tasks.team_llm_gateway_policy import update_team_llm_gateway_policy_cache_task


@override_settings(AI_GATEWAY_REDIS_URL="redis://localhost:6379/15")
class TestAccountTrustProjection(BaseTest):
    def read_blob(self, team: Team) -> dict[str, object]:
        raw = hypercache.cache_client.get(hypercache.get_cache_key(team))
        blob = json.loads(raw)
        assert isinstance(blob, dict)
        return blob

    def test_task_projects_current_org_state_even_with_a_cached_team(self) -> None:
        self.organization.customer_trust_scores = {"events": 7, "ai_credits": 3}
        self.organization.save(update_fields=["customer_trust_scores"])

        update_team_llm_gateway_policy_cache_task(self.team.id)

        self.assertEqual(
            self.read_blob(self.team),
            {
                "team_id": self.team.id,
                "organization_created_at": self.organization.created_at.isoformat(),
                "customer_trust_scores": {"events": 7, "ai_credits": 3},
            },
        )
        self.organization.customer_trust_scores = None
        self.organization.save(update_fields=["customer_trust_scores"])
        self.assertTrue(update_team_account_trust(self.team))
        self.assertIsNone(self.read_blob(self.team)["customer_trust_scores"])

    def test_score_change_invalidates_every_environment_and_refresh_recovers_a_missed_task(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="child")
        for team in [self.team, child]:
            self.assertTrue(update_team_account_trust(team))

        with (
            patch("posthog.tasks.team_llm_gateway_policy.update_team_llm_gateway_policy_cache_task.delay") as enqueue,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.organization.customer_trust_scores = {"events": 0}
            self.organization.save(update_fields=["customer_trust_scores"])

        self.assertEqual({call.args[0] for call in enqueue.call_args_list}, {self.team.id, child.id})
        for team in [self.team, child]:
            self.assertEqual(self.read_blob(team), {"team_id": team.id})

        refresh_account_trust_caches()
        for team in [self.team, child]:
            self.assertEqual(self.read_blob(team)["customer_trust_scores"], {"events": 0})

    def test_backfill_projects_all_teams_and_delete_removes_trust(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="child")
        call_command("llm_gateway_team", "project-trust", "--all", stdout=StringIO())
        for team in [self.team, child]:
            self.assertEqual(self.read_blob(team)["team_id"], team.id)
        key = hypercache.get_cache_key(child)
        child.delete()
        self.assertIsNone(hypercache.cache_client.get(key))
