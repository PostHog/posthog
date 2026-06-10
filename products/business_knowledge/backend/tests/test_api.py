from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource, SafetyVerdict


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


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestKnowledgeDocumentWindowAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.id}/business_knowledge/documents"

    def _ready_safe_document(self, *, paragraphs: int = 10, team=None) -> KnowledgeDocument:
        """Create a READY text source with exactly `paragraphs` chunks, all SAFE."""
        team = team or self.team
        # Each paragraph is padded past CHUNK_TARGET_CHARS (1200) but under
        # CHUNK_HARD_MAX_CHARS (1600) so the chunker emits one chunk per
        # paragraph — giving deterministic ordinals to window around.
        filler = "lorem ipsum dolor sit amet " * 50
        text = "\n\n".join(f"Paragraph {i}: {filler}" for i in range(paragraphs))
        source = logic.create_text_source(team_id=team.id, created_by_id=self.user.id, name="Docs", text=text)
        # create_text_source leaves the doc UNKNOWN (excluded from search/drill-down)
        # until the classifier clears it — mark SAFE so the window returns chunks.
        KnowledgeDocument.objects.unscoped().filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
        return KnowledgeDocument.objects.unscoped().get(source_id=source.id)

    def test_window_returns_contiguous_span(self, _ff) -> None:
        doc = self._ready_safe_document(paragraphs=10)
        response = self.client.get(f"{self.base}/{doc.id}/window/?around_ordinal=5&radius=2")
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        ordinals = [row["ordinal"] for row in body]
        assert ordinals == [3, 4, 5, 6, 7]
        first = body[0]
        assert set(first.keys()) == {
            "chunk_id",
            "ordinal",
            "content",
            "heading_path",
            "source_name",
            "document_title",
        }
        assert first["source_name"] == "Docs"

    def test_window_defaults_radius(self, _ff) -> None:
        doc = self._ready_safe_document(paragraphs=20)
        response = self.client.get(f"{self.base}/{doc.id}/window/?around_ordinal=10")
        assert response.status_code == status.HTTP_200_OK
        # Default radius is 5 -> ordinals 5..15.
        ordinals = [row["ordinal"] for row in response.json()]
        assert ordinals == list(range(5, 16))

    def test_window_requires_around_ordinal(self, _ff) -> None:
        doc = self._ready_safe_document()
        response = self.client.get(f"{self.base}/{doc.id}/window/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("attr") == "around_ordinal"

    def test_window_rejects_non_integer_params(self, _ff) -> None:
        doc = self._ready_safe_document()
        response = self.client.get(f"{self.base}/{doc.id}/window/?around_ordinal=abc")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("attr") == "around_ordinal"

    def test_window_unknown_document_is_404(self, _ff) -> None:
        import uuid

        response = self.client.get(f"{self.base}/{uuid.uuid4()}/window/?around_ordinal=0")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_window_invalid_uuid_is_404(self, _ff) -> None:
        response = self.client.get(f"{self.base}/not-a-uuid/window/?around_ordinal=0")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_window_cross_team_document_is_404(self, _ff) -> None:
        from posthog.models.team import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        theirs = self._ready_safe_document(team=other_team)
        response = self.client.get(f"{self.base}/{theirs.id}/window/?around_ordinal=0")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_window_excludes_unsafe_document(self, _ff) -> None:
        # A document that exists in the team but is not SAFE has no readable
        # chunks, so the window comes back empty (200, []), never leaking content.
        doc = self._ready_safe_document(paragraphs=5)
        KnowledgeDocument.objects.unscoped().filter(id=doc.id).update(safety_verdict=SafetyVerdict.UNSAFE)
        response = self.client.get(f"{self.base}/{doc.id}/window/?around_ordinal=2")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_window_feature_flag_gated(self, _ff) -> None:
        doc = self._ready_safe_document()
        _ff.return_value = False
        response = self.client.get(f"{self.base}/{doc.id}/window/?around_ordinal=0")
        assert response.status_code == status.HTTP_403_FORBIDDEN


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestKnowledgeDocumentWindowScopes(APIBaseTest):
    """The window endpoint is the BK MCP surface; MCP authenticates with a
    personal API key / OAuth token, so the custom action must enforce
    `business_knowledge:read` (not silently 403 every programmatic caller)."""

    def setUp(self) -> None:
        super().setUp()
        text = "\n\n".join(f"Paragraph {i}: {'lorem ipsum dolor sit amet ' * 50}" for i in range(5))
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Docs", text=text)
        KnowledgeDocument.objects.unscoped().filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
        self.doc = KnowledgeDocument.objects.unscoped().get(source_id=source.id)
        self.url = f"/api/projects/{self.team.id}/business_knowledge/documents/{self.doc.id}/window/?around_ordinal=2"

    def _auth_with_pak(self, scopes: list[str]) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

    def test_read_scope_allows_window(self, _ff) -> None:
        self._auth_with_pak(["business_knowledge:read"])
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK, response.content

    def test_wrong_scope_is_forbidden(self, _ff) -> None:
        self._auth_with_pak(["insight:read"])
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
