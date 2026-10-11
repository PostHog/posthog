import time_machine
from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.utils import timezone

from posthog.models.integration import Integration
from posthog.redis import get_client
from posthog.tasks.integrations import refresh_github_repository_cache


class TestGitHubRepositoryCacheRefresh(BaseTest):
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.list_repositories")
    def test_interrupted_worker_resumes_after_its_last_completed_page(self, mock_list_repositories):
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="456", config={})
        first_page = [{"id": 1, "name": "first", "full_name": "example/first"}]
        last_page = [{"id": 2, "name": "last", "full_name": "example/last"}]
        mock_list_repositories.side_effect = [(first_page, True), SystemExit("worker terminated"), (last_page, False)]

        with self.assertRaises(SystemExit):
            refresh_github_repository_cache.run(integration.id, self.team.id)

        integration.refresh_from_db()
        assert integration.repository_cache == []
        assert integration.repository_cache_updated_at is None

        refresh_github_repository_cache.run(integration.id, self.team.id)

        assert mock_list_repositories.call_args_list == [
            call(page=1, per_page=100),
            call(page=2, per_page=100),
            call(page=2, per_page=100),
        ]
        integration.refresh_from_db()
        assert integration.repository_cache == first_page + last_page
        assert integration.repository_cache_updated_at is not None

    @patch("posthog.tasks.integrations.refresh_github_repository_cache.apply_async")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.list_repositories")
    def test_budget_exhaustion_queues_the_next_chunk_and_publishes_only_the_full_scan(
        self, mock_list_repositories, mock_schedule
    ):
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="456", config={})
        first_page = [{"id": 1, "name": "first", "full_name": "example/first"}]
        last_page = [{"id": 2, "name": "last", "full_name": "example/last"}]
        mock_list_repositories.side_effect = [(first_page, True), (last_page, False)]

        with patch("posthog.tasks.github_repository_cache.monotonic", side_effect=[0, 0, 61]):
            refresh_github_repository_cache.run(integration.id, self.team.id)

        integration.refresh_from_db()
        assert integration.repository_cache == []
        assert integration.repository_cache_updated_at is None
        mock_schedule.assert_called_once_with(args=(integration.id, self.team.id), countdown=1)

        # Continuations are queued after releasing the lease, so the next worker can make progress.
        refresh_github_repository_cache.run(integration.id, self.team.id)

        assert mock_list_repositories.call_args_list == [call(page=1, per_page=100), call(page=2, per_page=100)]
        integration.refresh_from_db()
        assert integration.repository_cache == first_page + last_page
        assert integration.repository_cache_updated_at is not None
        assert not get_client().exists(f"github:repository_cache_refresh:{self.team.id}:{integration.id}:pages")

    @patch("posthog.tasks.integrations.refresh_github_repository_cache.apply_async")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.list_repositories")
    def test_reconnected_installation_discards_old_pagination(self, mock_list_repositories, mock_schedule):
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="456", config={})
        old_page = [{"id": 1, "name": "old", "full_name": "example/old"}]
        new_page = [{"id": 2, "name": "new", "full_name": "example/new"}]
        mock_list_repositories.side_effect = [(old_page, True), (new_page, False)]

        with patch("posthog.tasks.github_repository_cache.monotonic", side_effect=[0, 0, 61]):
            refresh_github_repository_cache.run(integration.id, self.team.id)

        Integration.objects.filter(id=integration.id).update(integration_id="789")
        refresh_github_repository_cache.run(integration.id, self.team.id)

        assert mock_list_repositories.call_args_list == [call(page=1, per_page=100), call(page=1, per_page=100)]
        integration.refresh_from_db()
        assert integration.repository_cache == new_page
        assert integration.repository_cache_updated_at is not None

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.list_repositories")
    def test_completed_checkpoint_survives_a_worker_exit_before_publication(self, mock_list_repositories):
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="456", config={})
        repositories = [{"id": 1, "name": "app", "full_name": "example/app"}]
        mock_list_repositories.return_value = (repositories, False)

        with patch("posthog.models.integration.model.IntegrationQuerySet.update", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                refresh_github_repository_cache.run(integration.id, self.team.id)

        mock_list_repositories.assert_called_once_with(page=1, per_page=100)
        integration.refresh_from_db()
        assert integration.repository_cache_updated_at is None

        refresh_github_repository_cache.run(integration.id, self.team.id)

        mock_list_repositories.assert_called_once_with(page=1, per_page=100)
        integration.refresh_from_db()
        assert integration.repository_cache == repositories
        assert integration.repository_cache_updated_at is not None

    @time_machine.travel("2026-10-09T12:00:00Z", tick=False)
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.list_repositories")
    def test_scan_does_not_overwrite_a_cache_refreshed_during_pagination(self, mock_list_repositories):
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="456", config={})
        newer_cache = [{"id": 2, "name": "new", "full_name": "example/new"}]
        refreshed_at = timezone.now()

        def finish_scan(**_kwargs):
            Integration.objects.filter(id=integration.id).update(
                repository_cache=newer_cache, repository_cache_updated_at=refreshed_at
            )
            return [{"id": 1, "name": "old", "full_name": "example/old"}], False

        mock_list_repositories.side_effect = finish_scan
        refresh_github_repository_cache.run(integration.id, self.team.id)

        integration.refresh_from_db()
        assert integration.repository_cache == newer_cache
        assert integration.repository_cache_updated_at == refreshed_at
