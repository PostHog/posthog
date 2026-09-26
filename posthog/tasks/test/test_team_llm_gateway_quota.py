from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models.organization import Organization
from posthog.redis import get_client
from posthog.storage.team_llm_gateway_quota_cache import (
    LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET,
    get_team_quota_blob,
    projected_team_ids,
    team_llm_gateway_quota_hypercache as hypercache,
)
from posthog.tasks.team_llm_gateway_quota import (
    project_org_llm_gateway_quota_task,
    project_teams_llm_gateway_quota_task,
    reconcile_llm_gateway_quota_projection,
)

from ee.billing.quota_limiting import (
    QuotaLimitingCaches,
    QuotaResource,
    add_limited_team_tokens,
    remove_limited_team_tokens,
)

_GATEWAY_REDIS_URL = "redis://localhost:6379/15"


class TestLLMGatewayQuotaTasks(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        hypercache.cache_client.clear()
        get_client(hypercache.redis_url).delete(LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET)
        remove_limited_team_tokens(
            QuotaResource.AI_CREDITS, [self.team.api_token], QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )

    def tearDown(self) -> None:
        remove_limited_team_tokens(
            QuotaResource.AI_CREDITS, [self.team.api_token], QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        super().tearDown()

    @patch("posthog.storage.team_llm_gateway_quota_cache.settings")
    def test_org_task_projects_every_team(self, mock_settings: MagicMock) -> None:
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        Organization.objects.filter(id=self.organization.id).update(is_active=False)
        with self.settings(AI_GATEWAY_REDIS_URL=_GATEWAY_REDIS_URL):
            project_org_llm_gateway_quota_task(str(self.organization.id))
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertTrue(blob["org_deactivated"])

    def test_org_task_ignores_a_missing_org(self) -> None:
        with self.settings(AI_GATEWAY_REDIS_URL=_GATEWAY_REDIS_URL):
            project_org_llm_gateway_quota_task("00000000-0000-0000-0000-000000000000")

    @patch("posthog.storage.team_llm_gateway_quota_cache.settings")
    def test_reconcile_task_projects_limited_teams(self, mock_settings: MagicMock) -> None:
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        add_limited_team_tokens(
            QuotaResource.AI_CREDITS,
            {self.team.api_token: int((timezone.now() + timedelta(days=2)).timestamp())},
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
        )
        with self.settings(AI_GATEWAY_REDIS_URL=_GATEWAY_REDIS_URL):
            reconcile_llm_gateway_quota_projection()
        self.assertEqual(projected_team_ids(), {self.team.id})

    @patch("posthog.storage.team_llm_gateway_quota_cache.settings")
    def test_teams_task_projects_the_teams_behind_the_tokens(self, mock_settings: MagicMock) -> None:
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        add_limited_team_tokens(
            QuotaResource.AI_CREDITS,
            {self.team.api_token: int((timezone.now() + timedelta(days=2)).timestamp())},
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
        )
        with self.settings(AI_GATEWAY_REDIS_URL=_GATEWAY_REDIS_URL):
            project_teams_llm_gateway_quota_task([self.team.api_token])
        self.assertEqual(projected_team_ids(), {self.team.id})

    def test_teams_task_noop_without_gateway_redis_url(self) -> None:
        with (
            self.settings(AI_GATEWAY_REDIS_URL=None),
            patch("posthog.tasks.team_llm_gateway_quota.project_teams_quota_by_token") as project,
        ):
            project_teams_llm_gateway_quota_task([self.team.api_token])
        project.assert_not_called()

    def test_reconcile_task_noop_without_gateway_redis_url(self) -> None:
        with (
            self.settings(AI_GATEWAY_REDIS_URL=None),
            patch("posthog.tasks.team_llm_gateway_quota.reconcile_quota_projection") as reconcile,
        ):
            reconcile_llm_gateway_quota_projection()
        reconcile.assert_not_called()

    def test_deactivating_an_org_enqueues_the_projection(self) -> None:
        with (
            self.settings(AI_GATEWAY_REDIS_URL=_GATEWAY_REDIS_URL),
            patch("posthog.tasks.team_llm_gateway_quota.project_org_llm_gateway_quota_task.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.organization.is_active = False
            self.organization.save()
        delay.assert_called_once_with(str(self.organization.id))

    def test_deactivating_an_org_enqueues_nothing_without_gateway_redis_url(self) -> None:
        with (
            self.settings(AI_GATEWAY_REDIS_URL=None),
            patch("posthog.tasks.team_llm_gateway_quota.project_org_llm_gateway_quota_task.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.organization.is_active = False
            self.organization.save()
        delay.assert_not_called()

    def test_saving_an_org_without_an_active_flip_enqueues_nothing(self) -> None:
        with (
            patch("posthog.tasks.team_llm_gateway_quota.project_org_llm_gateway_quota_task.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.organization.name = "renamed"
            self.organization.save()
        delay.assert_not_called()
