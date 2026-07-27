from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.api.serializers import _derive_scope_globs
from products.business_knowledge.backend.constants import CLASSIFY_MAX_ATTEMPTS
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

    def test_create_text_source_with_always_include(self, _ff) -> None:
        response = self.client.post(
            self.url,
            {"name": "Tone guide", "text": "Be friendly.", "always_include": True},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.json()["always_include"] is True

    def test_patch_always_include_without_text(self, _ff) -> None:
        create_resp = self.client.post(
            self.url,
            {"name": "Policy", "text": "Be nice."},
            format="json",
        )
        source_id = create_resp.json()["id"]
        patch_resp = self.client.patch(
            f"{self.url}{source_id}/",
            {"always_include": True},
            format="json",
        )
        assert patch_resp.status_code == status.HTTP_200_OK, patch_resp.content
        assert patch_resp.json()["always_include"] is True


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestEmbeddingStatusAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/business_knowledge/sources/"

    def _create_source(self) -> str:
        response = self.client.post(self.url, {"name": "Docs", "text": "Some content."}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.json()["id"]

    def test_fresh_source_is_pending(self, _ff) -> None:
        # The doc starts UNKNOWN — classification + embedding are still ahead,
        # and that must be visible from the create response already.
        response = self.client.post(self.url, {"name": "Docs", "text": "Some content."}, format="json")
        assert response.json()["embedding_status"] == "pending"

    @parameterized.expand(
        [
            ("awaiting_classification", SafetyVerdict.UNKNOWN, 0, False, "pending"),
            # Past the attempt cap the coordinator stops re-queuing — the doc
            # will never embed, so the source must not look pending forever.
            ("classification_gave_up", SafetyVerdict.UNKNOWN, CLASSIFY_MAX_ATTEMPTS, False, "completed"),
            ("awaiting_embedding_emit", SafetyVerdict.SAFE, 0, False, "pending"),
            ("embedded", SafetyVerdict.SAFE, 0, True, "completed"),
            ("unsafe_never_embeds", SafetyVerdict.UNSAFE, 0, False, "completed"),
        ]
    )
    def test_embedding_status_reflects_document_state(self, _ff, name, verdict, attempts, emitted, expected) -> None:
        source_id = self._create_source()
        KnowledgeDocument.objects.unscoped().filter(source_id=source_id).update(
            safety_verdict=verdict,
            classification_attempts=attempts,
            embeddings_emitted_at=timezone.now() if emitted else None,
        )
        retrieve = self.client.get(f"{self.url}{source_id}/").json()
        assert retrieve["embedding_status"] == expected, name
        listed = self.client.get(self.url).json()["results"]
        assert listed[0]["embedding_status"] == expected, name

    @parameterized.expand([("declined", False), ("undecided", None)])
    def test_disabled_when_org_has_not_approved_ai_processing(self, _ff, _name, approved) -> None:
        source_id = self._create_source()
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        response = self.client.get(f"{self.url}{source_id}/").json()
        assert response["embedding_status"] == "disabled"


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


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestKnowledgeDocumentSearchAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/business_knowledge/documents/search/"

    def _ready_safe_source(self, *, name: str = "Docs", text: str | None = None, team=None) -> KnowledgeSource:
        team = team or self.team
        if text is None:
            filler = "lorem ipsum dolor sit amet " * 50
            text = "\n\n".join(f"Paragraph {i}: {filler}" for i in range(5))
        source = logic.create_text_source(team_id=team.id, created_by_id=self.user.id, name=name, text=text)
        KnowledgeDocument.objects.unscoped().filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
        return source

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    def test_search_returns_ranked_chunks(self, _embed, _ff) -> None:
        self._ready_safe_source(
            text="Pricing plans are available on request.\n\n" + "x " * 600 + "\n\nOur refund policy is flexible."
        )
        response = self.client.get(self.url, {"query": "pricing"})
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert len(body) >= 1
        first = body[0]
        assert set(first.keys()) == {
            "chunk_id",
            "document_id",
            "ordinal",
            "source_id",
            "source_name",
            "source_type",
            "document_title",
            "heading_path",
            "content",
        }
        assert first["source_name"] == "Docs"
        assert "pricing" in first["content"].lower() or "Pricing" in first["content"]

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    def test_search_requires_query(self, _embed, _ff) -> None:
        self._ready_safe_source()
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("attr") == "query"

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    def test_search_rejects_blank_query(self, _embed, _ff) -> None:
        self._ready_safe_source()
        response = self.client.get(self.url, {"query": "   "})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    def test_search_cross_team_isolation(self, _embed, _ff) -> None:
        from posthog.models.team import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        self._ready_safe_source(name="Theirs", text="secret pricing data " * 60, team=other_team)
        response = self.client.get(self.url, {"query": "secret pricing"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    def test_search_excludes_unsafe_documents(self, _embed, _ff) -> None:
        source = self._ready_safe_source(text="Return policy details " * 60)
        KnowledgeDocument.objects.unscoped().filter(source_id=source.id).update(safety_verdict=SafetyVerdict.UNSAFE)
        response = self.client.get(self.url, {"query": "return policy"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_search_feature_flag_gated(self, _ff) -> None:
        _ff.return_value = False
        response = self.client.get(self.url, {"query": "anything"})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    def test_search_embedding_failure_falls_back_to_fts(self, _embed, _ff) -> None:
        self._ready_safe_source(text="Deployment guide for kubernetes " * 60)
        response = self.client.get(self.url, {"query": "kubernetes"})
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert len(body) >= 1
        assert "kubernetes" in body[0]["content"].lower()

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    @patch("products.business_knowledge.backend.logic.rerank_chunks")
    def test_search_rerank_param_calls_reranker(self, mock_rerank, _embed, _ff) -> None:
        self._ready_safe_source(text="Return policy details " * 60)
        mock_rerank.side_effect = lambda _team, query, results, *, top_k: list(reversed(results))

        response = self.client.get(self.url, {"query": "return policy", "rerank": "true"})
        assert response.status_code == status.HTTP_200_OK, response.content
        mock_rerank.assert_called_once()
        assert mock_rerank.call_args.kwargs["top_k"] == 10

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    def test_search_rerank_defaults_false(self, _embed, _ff) -> None:
        self._ready_safe_source(text="Return policy details " * 60)

        with patch("products.business_knowledge.backend.logic.rerank_chunks") as mock_rerank:
            response = self.client.get(self.url, {"query": "return policy"})
            assert response.status_code == status.HTTP_200_OK, response.content
            mock_rerank.assert_not_called()


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestKnowledgeDocumentSearchScopes(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        filler = "lorem ipsum dolor sit amet " * 50
        text = "\n\n".join(f"Paragraph {i}: {filler}" for i in range(3))
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Docs", text=text)
        KnowledgeDocument.objects.unscoped().filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
        self.url = f"/api/projects/{self.team.id}/business_knowledge/documents/search/?query=lorem"

    def _auth_with_pak(self, scopes: list[str]) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    def test_read_scope_allows_search(self, _embed, _ff) -> None:
        self._auth_with_pak(["business_knowledge:read"])
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK, response.content

    @patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
    def test_wrong_scope_is_forbidden(self, _embed, _ff) -> None:
        self._auth_with_pak(["insight:read"])
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestDeriveScopeGlobs(BaseTest):
    @parameterized.expand(
        [
            ("subpath", "https://posthog.com/docs/support", ["/docs/support", "/docs/support/*"]),
            ("deep_subpath", "https://example.com/a/b/c", ["/a/b/c", "/a/b/c/*"]),
            ("root_slash", "https://posthog.com/", []),
            ("root_no_slash", "https://posthog.com", []),
            ("trailing_slash_stripped", "https://example.com/docs/", ["/docs", "/docs/*"]),
        ]
    )
    def test_derivation(self, _name: str, url: str, expected: list[str]) -> None:
        assert _derive_scope_globs(url) == expected


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch("products.business_knowledge.backend.api.serializers.is_url_allowed", return_value=(True, None))
class TestCrawlSourceAutoScope(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.api_url = f"/api/projects/{self.team.id}/business_knowledge/sources/"

    @patch("products.business_knowledge.backend.api.views.KnowledgeSourceViewSet._start_background_ingest")
    @patch("products.business_knowledge.backend.api.views.logic.claim_url_source")
    def test_same_origin_derives_globs_from_entry_url(self, mock_claim, _bg, _url, _ff) -> None:
        mock_claim.return_value = KnowledgeSource(
            id="00000000-0000-0000-0000-000000000001",
            team=self.team,
            name="Support docs",
            source_type="url",
            status="processing",
            crawl_mode="same_origin",
            crawl_config={
                "include_globs": ["/docs/support", "/docs/support/*"],
                "exclude_globs": [],
                "max_pages": 50,
                "max_depth": 2,
            },
        )
        response = self.client.post(
            self.api_url,
            {
                "source_type": "url",
                "name": "Support docs",
                "url": "https://posthog.com/docs/support",
                "crawl_mode": "same_origin",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        call_kwargs = mock_claim.call_args.kwargs
        assert call_kwargs["crawl_config"]["include_globs"] == ["/docs/support", "/docs/support/*"]

    @patch("products.business_knowledge.backend.api.views.KnowledgeSourceViewSet._start_background_ingest")
    @patch("products.business_knowledge.backend.api.views.logic.claim_url_source")
    def test_explicit_include_globs_override_auto_scope(self, mock_claim, _bg, _url, _ff) -> None:
        mock_claim.return_value = KnowledgeSource(
            id="00000000-0000-0000-0000-000000000002",
            team=self.team,
            name="Custom",
            source_type="url",
            status="processing",
            crawl_mode="same_origin",
            crawl_config={"include_globs": ["/custom/*"], "exclude_globs": [], "max_pages": 50, "max_depth": 2},
        )
        response = self.client.post(
            self.api_url,
            {
                "source_type": "url",
                "name": "Custom",
                "url": "https://posthog.com/docs/support",
                "crawl_mode": "same_origin",
                "include_globs": ["/custom/*"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        call_kwargs = mock_claim.call_args.kwargs
        assert call_kwargs["crawl_config"]["include_globs"] == ["/custom/*"]

    @patch("products.business_knowledge.backend.api.views.KnowledgeSourceViewSet._start_background_ingest")
    @patch("products.business_knowledge.backend.api.views.logic.claim_url_source")
    def test_root_url_derives_empty_globs(self, mock_claim, _bg, _url, _ff) -> None:
        mock_claim.return_value = KnowledgeSource(
            id="00000000-0000-0000-0000-000000000003",
            team=self.team,
            name="Whole site",
            source_type="url",
            status="processing",
            crawl_mode="same_origin",
            crawl_config={"include_globs": [], "exclude_globs": [], "max_pages": 50, "max_depth": 2},
        )
        response = self.client.post(
            self.api_url,
            {
                "source_type": "url",
                "name": "Whole site",
                "url": "https://posthog.com/",
                "crawl_mode": "same_origin",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        call_kwargs = mock_claim.call_args.kwargs
        assert call_kwargs["crawl_config"]["include_globs"] == []

    @patch("products.business_knowledge.backend.api.views.KnowledgeSourceViewSet._start_background_ingest")
    @patch("products.business_knowledge.backend.api.views.logic.update_url_source")
    def test_update_url_rederives_globs_when_not_sent(self, mock_update, _bg, _url, _ff) -> None:
        source = KnowledgeSource.objects.unscoped().create(
            id="00000000-0000-0000-0000-000000000004",
            team=self.team,
            name="Old source",
            source_type="url",
            status="ready",
            source_url="https://posthog.com/docs/old",
            crawl_mode="same_origin",
            crawl_config={
                "include_globs": ["/docs/old", "/docs/old/*"],
                "exclude_globs": [],
                "max_pages": 50,
                "max_depth": 2,
            },
        )
        mock_update.return_value = source
        response = self.client.patch(
            f"{self.api_url}{source.id}/",
            {
                "url": "https://posthog.com/docs/new",
                "crawl_mode": "same_origin",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs["crawl_config"]["include_globs"] == ["/docs/new", "/docs/new/*"]
