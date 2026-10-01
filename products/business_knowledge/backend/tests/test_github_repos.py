from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models.integration import Integration
from posthog.models.integration_repository_cache import IntegrationRepositoryCacheEntry
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.business_knowledge.backend.models import TeamBusinessKnowledgeConfig

BILLING = "acme/billing"
OTHER = "acme/other"


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch("posthoganalytics.capture")
class TestBusinessKnowledgeGithubRepos(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.id}/business_knowledge/repositories"
        self.integration = self._github_integration(self.team)
        self.warm = patch(
            "products.business_knowledge.backend.tasks.tasks.warm_business_knowledge_github_repo.delay"
        ).start()
        self.installation_repos = patch(
            "products.business_knowledge.backend.github_repos.GitHubIntegration.list_all_cached_repositories",
            return_value=[{"full_name": BILLING}, {"full_name": OTHER}],
        ).start()
        self.addCleanup(patch.stopall)

    def _github_integration(self, team) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="github",
            integration_id=f"inst-{team.id}",
            config={"account": {"name": "Acme"}},
            created_by=self.user,
        )

    def _select(self, repos: list[str], *, listed: list[str] | None = None):
        names = listed if listed is not None else repos
        with (
            patch(
                "products.business_knowledge.backend.github_repos.GitHubIntegration.list_all_cached_repositories",
                return_value=[{"full_name": name} for name in names],
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            return self.client.post(f"{self.base}/selection/", {"repos": repos}, format="json")

    def _connect(self, integration_id: int | None = None):
        return self.client.post(
            f"{self.base}/connect/",
            {"integration_id": self.integration.id if integration_id is None else integration_id},
            format="json",
        )

    def _cache(self, team, integration: Integration, full_name: str, *, tree_paths: str, readme: str = "") -> None:
        IntegrationRepositoryCacheEntry.objects.create(
            team=team,
            integration=integration,
            full_name=full_name,
            default_branch="main",
            default_branch_sha="abc123",
            tree_paths=tree_paths,
            readme=readme,
        )

    def test_select_rejects_unknown_bad_and_too_many_repos(self, _capture, _flag) -> None:
        self._connect()
        unknown = self._select(["acme/missing"], listed=[BILLING])
        assert unknown.status_code == 400
        assert "not available" in str(unknown.json())

        bad = self._select(["not a repo"], listed=[BILLING])
        assert bad.status_code == 400
        assert "owner/repo" in str(bad.json())

        too_many = self._select([f"acme/repo-{index}" for index in range(21)])
        assert too_many.status_code == 400

    def test_connect_rejects_another_teams_installation(self, _capture, _flag) -> None:
        other = self._github_integration(self._other_team())
        response = self._connect(other.id)
        assert response.status_code == 400
        assert get_or_create_team_extension(self.team, TeamBusinessKnowledgeConfig).github_integration_id is None

    def test_select_stores_lowercased_names(self, _capture, _flag) -> None:
        self._connect()
        response = self._select(["Acme/Billing"], listed=["Acme/Billing"])
        assert response.status_code == 200, response.json()
        assert response.json()["repos"] == [BILLING]
        assert self.warm.called

    def test_search_stays_inside_the_allowlist(self, _capture, _flag) -> None:
        self._connect()
        assert self._select([BILLING], listed=[BILLING, OTHER]).status_code == 200
        self._cache(
            self.team, self.integration, BILLING, tree_paths="src/billing.py\nREADME.md", readme="Billing prorates."
        )
        self._cache(self.team, self.integration, OTHER, tree_paths="src/billing.py")
        other_team = self._other_team()
        other_integration = self._github_integration(other_team)
        self._cache(other_team, other_integration, BILLING, tree_paths="src/secret.py")
        self.warm.reset_mock()

        response = self.client.get(f"{self.base}/search/", {"query": "billing"})
        assert response.status_code == 200, response.json()
        paths = [hit["path"] for hit in response.json()["results"] if hit["kind"] == "path"]
        assert paths == ["src/billing.py"]
        assert all(hit["repo"] == BILLING for hit in response.json()["results"])
        readme_urls = [hit["url"] for hit in response.json()["results"] if hit["kind"] == "readme"]
        assert readme_urls == ["https://github.com/acme/billing/tree/abc123#readme"]
        assert self.warm.called is False

    def test_repository_removed_from_installation_is_not_searchable(self, _capture, _flag) -> None:
        self._connect()
        assert self._select([BILLING, OTHER]).status_code == 200
        self._cache(self.team, self.integration, BILLING, tree_paths="src/billing.py", readme="Billing prorates.")
        self._cache(self.team, self.integration, OTHER, tree_paths="src/billing_other.py")
        self.installation_repos.return_value = [{"full_name": OTHER}]

        search = self.client.get(f"{self.base}/search/", {"query": "billing"})
        assert search.status_code == 200, search.json()
        assert {hit["repo"] for hit in search.json()["results"]} == {OTHER}
        scoped = self.client.get(f"{self.base}/search/", {"query": "billing", "repo": BILLING})
        assert scoped.status_code == 400
        read = self.client.get(f"{self.base}/file/", {"repo": BILLING, "path": "src/billing.py"})
        assert read.status_code == 400

        self.installation_repos.return_value = []
        assert self.client.get(f"{self.base}/search/", {"query": "billing"}).status_code == 400

    def test_search_enqueues_one_refresh_for_a_stale_cache(self, _capture, _flag) -> None:
        # Set the allowlist directly. Selection also queues a warm and would trip the debounce.
        config = get_or_create_team_extension(self.team, TeamBusinessKnowledgeConfig)
        config.github_integration_id = self.integration.id
        config.github_repos = [BILLING]
        config.save(update_fields=["github_integration_id", "github_repos"])
        self._cache(self.team, self.integration, BILLING, tree_paths="src/billing.py")
        IntegrationRepositoryCacheEntry.objects.filter(full_name=BILLING).update(
            updated_at=timezone.now() - timedelta(hours=2)
        )
        self.warm.reset_mock()

        first = self.client.get(f"{self.base}/search/", {"query": "billing"})
        second = self.client.get(f"{self.base}/search/", {"query": "billing"})
        assert first.status_code == 200
        assert first.json()["repositories"] == [{"repo": BILLING, "tree_truncated": False, "cache_status": "warming"}]
        assert second.status_code == 200
        assert self.warm.call_count == 1

    def test_file_read_rejects_paths_outside_the_cached_tree(self, _capture, _flag) -> None:
        self._connect()
        self._select([BILLING], listed=[BILLING])
        self._cache(self.team, self.integration, BILLING, tree_paths="src/billing.py")
        with patch(
            "products.business_knowledge.backend.github_repos.GitHubIntegration.get_file_contents",
            return_value={"content": "def prorate():\n    return 1\n", "sha": "abc123"},
        ) as read:
            missing = self.client.get(f"{self.base}/file/", {"repo": BILLING, "path": "../secrets"})
            directory = self.client.get(f"{self.base}/file/", {"repo": BILLING, "path": "src"})
            off_list = self.client.get(f"{self.base}/file/", {"repo": OTHER, "path": "src/billing.py"})
            assert missing.status_code == 400
            assert directory.status_code == 400
            assert off_list.status_code == 400
            read.assert_not_called()

            found = self.client.get(f"{self.base}/file/", {"repo": BILLING, "path": "src/billing.py"})
        assert found.status_code == 200, found.json()
        assert found.json()["content"].startswith("def prorate")
        assert found.json()["url"] == "https://github.com/acme/billing/blob/abc123/src/billing.py"
        read.assert_called_once_with(BILLING, "src/billing.py", ref="abc123")

    def _other_team(self) -> Team:
        return Team.objects.create(organization=self.organization, name="Other environment")
