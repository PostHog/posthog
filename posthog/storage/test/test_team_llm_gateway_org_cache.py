"""The per-team organization entry the Go ai-gateway reads for org-wallet admission."""

import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import override_settings

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.storage.team_llm_gateway_org_cache import (
    _batch_load_llm_gateway_org,
    clear_team_llm_gateway_org_cache,
    get_team_llm_gateway_org,
    team_llm_gateway_org_hypercache,
    update_organization_llm_gateway_org_cache,
    update_team_llm_gateway_org_cache,
)

GATEWAY_REDIS = "redis://localhost:6379/1"
PERIOD = ["2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"]


class TestLLMGatewayOrgEntry(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization.usage = {
            "period": PERIOD,
            "ai_monthly_spend_limit_usd": "250.00",
            "ai_low_balance_threshold_usd": "5.00",
            "ai_automatic_reload_enabled": True,
        }
        self.organization.customer_trust_scores = {"ai_credits": 10}
        self.organization.save()

    def _expected(self, team: Team) -> dict:
        return {
            "version": 1,
            "team_id": team.id,
            "organization_id": str(self.organization.id),
            "billing_period": {"start": PERIOD[0], "end": PERIOD[1]},
            "ai_monthly_spend_limit_usd": "250.00",
            "ai_low_balance_threshold_usd": "5.00",
            "ai_automatic_reload_enabled": True,
            "customer_trust_scores": {"ai_credits": 10},
        }

    def test_the_entry_carries_the_organization_and_its_settings(self):
        update_team_llm_gateway_org_cache(self.team)

        entry = get_team_llm_gateway_org(self.team)

        assert entry == self._expected(self.team)
        assert json.loads(json.dumps(entry)) == entry

    def test_an_organization_without_settings_has_nulls(self):
        self.organization.usage = None
        self.organization.customer_trust_scores = {}
        self.organization.save()

        update_team_llm_gateway_org_cache(self.team)

        assert get_team_llm_gateway_org(self.team) == {
            "version": 1,
            "team_id": self.team.id,
            "organization_id": str(self.organization.id),
            "billing_period": None,
            "ai_monthly_spend_limit_usd": None,
            "ai_low_balance_threshold_usd": None,
            "ai_automatic_reload_enabled": False,
            "customer_trust_scores": {},
        }

    def test_an_organization_update_rewrites_every_team(self):
        other = Team.objects.create(organization=self.organization, name="Second")
        clear_team_llm_gateway_org_cache(self.team, kinds=["redis"])

        written = update_organization_llm_gateway_org_cache(self.organization.id)

        assert written == 2
        assert get_team_llm_gateway_org(self.team) == self._expected(self.team)
        assert get_team_llm_gateway_org(other) == self._expected(other)

    def test_a_missing_entry_loads_from_the_database(self):
        clear_team_llm_gateway_org_cache(self.team, kinds=["redis"])

        assert get_team_llm_gateway_org(self.team) == self._expected(self.team)

    def test_the_batch_loader_reads_each_organization_once(self):
        other = Team.objects.create(organization=self.organization, name="Second")

        with self.assertNumQueries(1):
            entries = _batch_load_llm_gateway_org([self.team, other])

        assert entries == {self.team.id: self._expected(self.team), other.id: self._expected(other)}

    @override_settings(AI_GATEWAY_REDIS_URL=GATEWAY_REDIS)
    def test_the_backfill_writes_every_team(self):
        clear_team_llm_gateway_org_cache(self.team, kinds=["redis"])

        call_command("warm_llm_gateway_org_cache", "--no-stagger", stdout=MagicMock())

        raw = team_llm_gateway_org_hypercache.cache_client.get(team_llm_gateway_org_hypercache.get_cache_key(self.team))
        assert json.loads(raw) == self._expected(self.team)


class TestLLMGatewayOrgSignals(BaseTest):
    @override_settings(AI_GATEWAY_REDIS_URL=GATEWAY_REDIS)
    @patch("posthog.tasks.team_llm_gateway_org.update_team_llm_gateway_org_cache_task.delay")
    def test_a_new_team_gets_its_entry(self, delay: MagicMock):
        with self.captureOnCommitCallbacks(execute=True):
            team = Team.objects.create(organization=self.organization, name="New")

        delay.assert_called_once_with(team.id)

    @override_settings(AI_GATEWAY_REDIS_URL=GATEWAY_REDIS)
    @patch("posthog.tasks.team_llm_gateway_org.update_team_llm_gateway_org_cache_task.delay")
    def test_saving_an_existing_team_changes_nothing(self, delay: MagicMock):
        with self.captureOnCommitCallbacks(execute=True):
            self.team.name = "Renamed"
            self.team.save()

        delay.assert_not_called()

    @override_settings(AI_GATEWAY_REDIS_URL=GATEWAY_REDIS)
    @patch("posthog.tasks.team_llm_gateway_org.update_team_llm_gateway_org_cache_task.delay")
    def test_a_team_moved_to_another_organization_gets_its_entry(self, delay: MagicMock):
        other = Organization.objects.create(name="Other")
        team = Team.objects.get(id=self.team.id)

        with self.captureOnCommitCallbacks(execute=True):
            team.organization_id = other.id
            team.save()

        delay.assert_called_once_with(team.id)

    @override_settings(AI_GATEWAY_REDIS_URL=GATEWAY_REDIS)
    def test_a_deleted_team_loses_its_entry(self):
        team = Team.objects.create(organization=self.organization, name="Doomed")
        update_team_llm_gateway_org_cache(team)
        key = team_llm_gateway_org_hypercache.get_cache_key(team)

        team.delete()

        assert team_llm_gateway_org_hypercache.cache_client.get(key) is None
