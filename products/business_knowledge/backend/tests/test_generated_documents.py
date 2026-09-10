import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.team import Team

from products.business_knowledge.backend import generated_documents, logic
from products.business_knowledge.backend.facade import api
from products.business_knowledge.backend.facade.contracts import (
    CreateGeneratedKnowledgeDocument,
    GeneratedKnowledgeDocument,
)
from products.business_knowledge.backend.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SafetyVerdict,
    SourceStatus,
    SourceType,
)


class TestGeneratedKnowledgeDocuments(BaseTest):
    def _input(
        self,
        *,
        team_id: int | None = None,
        resolution_comment_id: uuid.UUID | None = None,
        analysis_version: str = "post_resolution_v1",
        title: str = "Refund policy",
        content: str = "Refunds are available within 30 days.",
    ) -> CreateGeneratedKnowledgeDocument:
        return CreateGeneratedKnowledgeDocument(
            team_id=team_id or self.team.id,
            ticket_id=uuid.UUID("10000000-0000-0000-0000-000000000001"),
            resolution_comment_id=resolution_comment_id or uuid.UUID("20000000-0000-0000-0000-000000000002"),
            analysis_version=analysis_version,
            title=title,
            content=content,
        )

    def test_creates_generated_source_document_and_chunks(self) -> None:
        input = self._input()

        result = api.create_generated_knowledge_document(input)

        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        chunks = list(KnowledgeChunk.objects.unscoped().filter(document=document))
        provenance = {
            "origin": generated_documents.GENERATED_KNOWLEDGE_ORIGIN,
            "ticket_id": str(input.ticket_id),
            "resolution_comment_id": str(input.resolution_comment_id),
            "analysis_version": input.analysis_version,
        }

        assert result.created is True
        assert source.team_id == self.team.id
        assert source.name == generated_documents.GENERATED_SOURCE_NAME
        assert source.source_type == SourceType.TEXT
        assert source.is_generated is True
        assert source.status == SourceStatus.READY
        assert source.created_by_id is None
        assert document.safety_verdict == SafetyVerdict.UNKNOWN
        assert document.metadata == {"source_type": SourceType.TEXT, **provenance}
        assert chunks
        assert logic.search_knowledge(self.team.id, "refunds") == []

        searchable_text = "\n".join(
            [source.name, document.title, document.content, *(chunk.content for chunk in chunks)]
        )
        assert str(input.ticket_id) not in searchable_text
        assert str(input.resolution_comment_id) not in searchable_text
        assert input.analysis_version not in searchable_text

    def test_retry_returns_existing_document_without_rewriting_it(self) -> None:
        first = api.create_generated_knowledge_document(self._input())

        retry = api.create_generated_knowledge_document(
            self._input(title="Changed title", content="Changed content that must not replace the original.")
        )

        document = KnowledgeDocument.objects.unscoped().get(id=first.id)
        assert retry == GeneratedKnowledgeDocument(
            id=first.id,
            source_id=first.source_id,
            created=False,
        )
        assert document.title == "Refund policy"
        assert document.content == "Refunds are available within 30 days."
        assert KnowledgeSource.objects.unscoped().filter(team=self.team, is_generated=True).count() == 1
        assert KnowledgeDocument.objects.unscoped().filter(source_id=first.source_id).count() == 1

    def test_new_analysis_revision_reuses_team_source(self) -> None:
        first = api.create_generated_knowledge_document(self._input())
        second = api.create_generated_knowledge_document(self._input(analysis_version="post_resolution_v2"))

        assert first.source_id == second.source_id
        assert first.id != second.id
        assert KnowledgeSource.objects.unscoped().filter(team=self.team, is_generated=True).count() == 1
        assert KnowledgeDocument.objects.unscoped().filter(source_id=first.source_id).count() == 2

    def test_same_provenance_is_isolated_between_teams(self) -> None:
        other_team = Team.objects.create_with_data(
            organization=self.organization,
            initiating_user=self.user,
            name="Other",
        )

        mine = api.create_generated_knowledge_document(self._input())
        theirs = api.create_generated_knowledge_document(self._input(team_id=other_team.id))

        assert mine.source_id != theirs.source_id
        assert mine.id != theirs.id
        assert KnowledgeDocument.objects.unscoped().get(id=mine.id).team_id == self.team.id
        assert KnowledgeDocument.objects.unscoped().get(id=theirs.id).team_id == other_team.id

    def test_disabling_generated_source_removes_it_from_search_without_deleting_data(self) -> None:
        result = api.create_generated_knowledge_document(self._input())
        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        logic.set_document_safety(
            team_id=self.team.id,
            document_id=document.id,
            verdict=SafetyVerdict.SAFE,
            content_hash=document.content_hash,
        )
        assert logic.search_knowledge(self.team.id, "refunds")

        assert api.set_generated_knowledge_source_ready(self.team.id, ready=False) is True

        assert logic.search_knowledge(self.team.id, "refunds") == []
        assert KnowledgeDocument.objects.unscoped().filter(id=result.id).exists()
        assert KnowledgeChunk.objects.unscoped().filter(document_id=result.id).exists()

    def test_generated_source_does_not_consume_user_source_quota(self) -> None:
        api.create_generated_knowledge_document(self._input())

        with patch.object(logic, "MAX_SOURCES_PER_TEAM", 1):
            logic.create_text_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="User source",
                text="User-authored content",
            )
            with self.assertRaises(logic.QuotaExceededError):
                logic.create_text_source(
                    team_id=self.team.id,
                    created_by_id=self.user.id,
                    name="Second user source",
                    text="More user-authored content",
                )

    def test_chunk_quota_failure_rolls_back_new_source(self) -> None:
        with (
            patch.object(generated_documents, "MAX_CHUNKS_PER_TEAM", 0),
            self.assertRaises(api.GeneratedKnowledgeDocumentQuotaExceededError),
        ):
            api.create_generated_knowledge_document(self._input())

        assert not KnowledgeSource.objects.unscoped().filter(team=self.team, is_generated=True).exists()

    @parameterized.expand(
        [
            (
                "title",
                "x" * (generated_documents.MAX_DOCUMENT_TITLE_LENGTH + 1),
                "Valid content",
            ),
            (
                "content",
                "Valid title",
                "x" * (generated_documents.MAX_TEXT_SIZE_BYTES + 1),
            ),
        ]
    )
    def test_rejects_unbounded_document_fields(self, _name: str, title: str, content: str) -> None:
        with self.assertRaises(api.GeneratedKnowledgeDocumentInvalidInputError):
            api.create_generated_knowledge_document(self._input(title=title, content=content))
