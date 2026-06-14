from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from ...models.community_skills import CommunitySkill, CommunitySkillFile, CommunitySkillVote
from ...models.skills import LLMSkill
from ..community_skill_services import sync_community_skills_from_github


def _create_community_skill(
    *,
    slug: str = "web-analytics-triage",
    name: str = "Web analytics triage",
    trust_tier: str = "official",
    install_count: int = 0,
    deleted: bool = False,
) -> CommunitySkill:
    return CommunitySkill.objects.create(
        slug=slug,
        name=name,
        description="Investigate a change in web traffic.",
        body="# Triage\nDo the thing.",
        trust_tier=trust_tier,
        tags=["web-analytics"],
        install_count=install_count,
        deleted=deleted,
    )


@patch(
    "products.ai_observability.backend.api.community_skills.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestCommunitySkillAPI(APIBaseTest):
    def _url(self, path: str = "") -> str:
        return f"/api/projects/{self.team.id}/community_skills/{path}"

    def test_list_returns_published_skills_ordered_by_installs(self, _mock_flag) -> None:
        _create_community_skill(slug="alpha", install_count=1)
        _create_community_skill(slug="beta", install_count=5)

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual([s["slug"] for s in results], ["beta", "alpha"])
        self.assertNotIn("body", results[0])  # list serializer omits body

    def test_list_excludes_deleted(self, _mock_flag) -> None:
        _create_community_skill(slug="visible")
        _create_community_skill(slug="gone", deleted=True)

        response = self.client.get(self._url())
        self.assertEqual([s["slug"] for s in response.json()["results"]], ["visible"])

    def test_filter_by_trust_tier(self, _mock_flag) -> None:
        _create_community_skill(slug="official-one", trust_tier="official")
        _create_community_skill(slug="community-one", trust_tier="community")

        response = self.client.get(self._url(), {"trust_tier": "community"})
        self.assertEqual([s["slug"] for s in response.json()["results"]], ["community-one"])

    def test_retrieve_by_slug_includes_body(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")
        response = self.client.get(self._url("web-analytics-triage/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["body"], "# Triage\nDo the thing.")

    def test_install_creates_team_skill_and_increments_count(self, _mock_flag) -> None:
        skill = _create_community_skill(slug="web-analytics-triage")
        CommunitySkillFile.objects.create(skill=skill, path="references/playbook.md", content="hints")

        response = self.client.post(self._url("web-analytics-triage/install/"), {})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        installed = LLMSkill.objects.get(team=self.team, name="web-analytics-triage")
        self.assertEqual(installed.body, "# Triage\nDo the thing.")
        self.assertEqual(installed.metadata["community_skill_slug"], "web-analytics-triage")
        self.assertEqual(installed.files.count(), 1)

        skill.refresh_from_db()
        self.assertEqual(skill.install_count, 1)

    def test_install_with_custom_name(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")
        response = self.client.post(self._url("web-analytics-triage/install/"), {"new_name": "my-triage"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertTrue(LLMSkill.objects.filter(team=self.team, name="my-triage").exists())

    def test_install_name_conflict_returns_400(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")
        LLMSkill.objects.create(team=self.team, name="web-analytics-triage", description="x", body="y")

        response = self.client.post(self._url("web-analytics-triage/install/"), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_install_unknown_slug_returns_404(self, _mock_flag) -> None:
        response = self.client.post(self._url("does-not-exist/install/"), {})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_vote_toggles_on_and_off(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")

        first = self.client.post(self._url("web-analytics-triage/vote/"))
        self.assertEqual(first.json(), {"vote_count": 1, "has_voted": True})

        second = self.client.post(self._url("web-analytics-triage/vote/"))
        self.assertEqual(second.json(), {"vote_count": 0, "has_voted": False})
        self.assertFalse(CommunitySkillVote.objects.exists())


class TestCommunitySkillSync(APIBaseTest):
    @patch("products.ai_observability.backend.api.community_skill_services.requests.get")
    def test_sync_upserts_and_soft_deletes_missing(self, mock_get) -> None:
        _create_community_skill(slug="stale-skill", install_count=3)

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "version": 1,
            "skills": [
                {
                    "slug": "fresh-skill",
                    "name": "Fresh skill",
                    "description": "New one",
                    "body": "# Fresh",
                    "trust_tier": "community",
                    "source_sha": "abc123",
                    "files": [{"path": "ref.md", "content": "x"}],
                }
            ],
        }

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 1, "skipped": 0, "removed": 1})

        fresh = CommunitySkill.objects.get(slug="fresh-skill")
        self.assertEqual(fresh.files.count(), 1)
        self.assertFalse(fresh.deleted)
        self.assertIsNotNone(fresh.published_at)

        self.assertTrue(CommunitySkill.objects.get(slug="stale-skill").deleted)

    @patch("products.ai_observability.backend.api.community_skill_services.requests.get")
    def test_sync_skips_unchanged_sha(self, mock_get) -> None:
        existing = _create_community_skill(slug="web-analytics-triage")
        CommunitySkill.objects.filter(pk=existing.pk).update(source_sha="same-sha")

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [
                {
                    "slug": "web-analytics-triage",
                    "name": "Web analytics triage",
                    "description": "Investigate a change in web traffic.",
                    "source_sha": "same-sha",
                }
            ],
        }

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 0, "skipped": 1, "removed": 0})

    @patch("products.ai_observability.backend.api.community_skill_services.requests.get")
    def test_sync_empty_registry_does_not_wipe_catalog(self, mock_get) -> None:
        _create_community_skill(slug="keep-me")

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {"skills": []}

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 0, "skipped": 0, "removed": 0})
        self.assertFalse(CommunitySkill.objects.get(slug="keep-me").deleted)
