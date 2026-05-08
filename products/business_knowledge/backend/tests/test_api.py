from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestKnowledgeSourceAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/business_knowledge/sources/"

    def test_create_text_source_and_chunks(self, _ff) -> None:
        response = self.client.post(
            self.url,
            {"name": "Docs", "text": "Intro paragraph.\n\nSecond paragraph covers pricing."},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["name"] == "Docs"
        assert body["source_type"] == "text"
        assert body["status"] == "ready"
        assert body["document_count"] == 1
        assert body["chunk_count"] >= 1
        # Denormalized team_id landed on child rows.
        source = KnowledgeSource.objects.unscoped().get(id=body["id"])
        assert KnowledgeDocument.objects.unscoped().filter(source=source, team=self.team).count() == 1
        assert KnowledgeChunk.objects.unscoped().filter(source=source, team=self.team).count() >= 1

    def test_list_only_returns_own_team(self, _ff) -> None:
        from posthog.models.team import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        # Create in THIS team via API.
        self.client.post(self.url, {"name": "Mine", "text": "hello"}, format="json")
        # Create directly in the other team — unscoped to bypass TeamScopedManager.
        KnowledgeSource.objects.unscoped().create(team=other_team, name="Theirs", source_type="text", status="ready")

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        names = [row["name"] for row in response.json()["results"]]
        assert names == ["Mine"]

    def test_cannot_read_other_team_source_via_id(self, _ff) -> None:
        from posthog.models.team import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        theirs = KnowledgeSource.objects.unscoped().create(
            team=other_team, name="Theirs", source_type="text", status="ready"
        )
        response = self.client.get(f"{self.url}{theirs.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_delete_other_team_source(self, _ff) -> None:
        from posthog.models.team import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        theirs = KnowledgeSource.objects.unscoped().create(
            team=other_team, name="Theirs", source_type="text", status="ready"
        )
        response = self.client.delete(f"{self.url}{theirs.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        # Untouched.
        assert KnowledgeSource.objects.unscoped().filter(id=theirs.id).exists()

    def test_delete_cascades_and_fires_activity_log(self, _ff) -> None:
        create = self.client.post(self.url, {"name": "Docs", "text": "body"}, format="json").json()
        source_id = create["id"]
        assert KnowledgeDocument.objects.unscoped().filter(source_id=source_id).exists()
        assert KnowledgeChunk.objects.unscoped().filter(source_id=source_id).exists()

        response = self.client.delete(f"{self.url}{source_id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not KnowledgeSource.objects.unscoped().filter(id=source_id).exists()
        assert not KnowledgeDocument.objects.unscoped().filter(source_id=source_id).exists()
        assert not KnowledgeChunk.objects.unscoped().filter(source_id=source_id).exists()
        # Activity logging hook ran.
        assert ActivityLog.objects.filter(scope="KnowledgeSource", item_id=source_id, activity="deleted").exists()

    def test_rejects_empty_text(self, _ff) -> None:
        response = self.client.post(self.url, {"name": "Docs", "text": "   "}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        # drf-exceptions-hog normalizes single-field errors into a flat
        # {type, code, detail, attr} shape; we assert the offending field
        # lands in `attr` so UX code can still target it.
        assert body.get("attr") == "text"

    def test_rejects_oversized_text(self, _ff) -> None:
        response = self.client.post(self.url, {"name": "Docs", "text": "x" * 1_000_001}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("attr") == "text"

    def test_create_defaults_source_type_to_text(self, _ff) -> None:
        # Stage 2a dispatches on `source_type`. Omitting it must still land
        # on the text path so Stage 1 clients keep working unchanged.
        response = self.client.post(self.url, {"name": "Docs", "text": "hello"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["source_type"] == "text"
