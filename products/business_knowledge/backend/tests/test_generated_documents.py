import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.team import Team

from products.business_knowledge.backend import logic
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
        provider: str = "conversations",
        ticket_number: int = 42,
        source_team_id: int | None = None,
        resolution_comment_id: uuid.UUID | None = None,
        analysis_version: str = "post_resolution_v1",
        title: str = "Refund policy",
        content: str = "Refunds are available within 30 days.",
    ) -> logic.CreateGeneratedKnowledgeDocument:
        return logic.CreateGeneratedKnowledgeDocument(
            team_id=team_id or self.team.id,
            provider=provider,
            ticket_id=uuid.UUID("10000000-0000-0000-0000-000000000001"),
            ticket_number=ticket_number,
            source_team_id=source_team_id if source_team_id is not None else (team_id or self.team.id),
            resolution_comment_id=resolution_comment_id or uuid.UUID("20000000-0000-0000-0000-000000000002"),
            analysis_version=analysis_version,
            title=title,
            content=content,
        )

    def test_creates_generated_source_document_and_chunks(self) -> None:
        input = self._input()

        result = logic.create_generated_knowledge_document(input)

        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        chunks = list(KnowledgeChunk.objects.unscoped().filter(document=document))
        provenance = {
            "origin": logic.GENERATED_KNOWLEDGE_ORIGIN,
            "provider": input.provider,
            "ticket_id": str(input.ticket_id),
            "ticket_number": input.ticket_number,
            "source_team_id": input.source_team_id,
            "resolution_comment_id": str(input.resolution_comment_id),
            "analysis_version": input.analysis_version,
        }

        assert result.created is True
        assert source.team_id == self.team.id
        assert source.name == logic.GENERATED_SOURCE_NAME
        assert source.source_type == SourceType.TEXT
        assert source.is_generated is True
        assert source.status == SourceStatus.READY
        assert source.created_by_id is None
        assert document.safety_verdict == SafetyVerdict.UNKNOWN
        assert document.metadata == {"source_type": SourceType.TEXT, **provenance}
        assert chunks
        assert logic.search_knowledge(self.team.id, "refunds") == []

        searchable_text = "\n".join(
            [source.name, document.stable_id, document.title, document.content, *(chunk.content for chunk in chunks)]
        )
        assert str(input.ticket_id) not in searchable_text
        assert str(input.resolution_comment_id) not in searchable_text
        assert input.analysis_version not in searchable_text

    def test_retry_returns_existing_document_without_rewriting_it(self) -> None:
        first = logic.create_generated_knowledge_document(self._input())

        retry = logic.create_generated_knowledge_document(
            self._input(title="Changed title", content="Changed content that must not replace the original.")
        )

        document = KnowledgeDocument.objects.unscoped().get(id=first.id)
        assert retry == logic.GeneratedKnowledgeDocument(
            id=first.id,
            source_id=first.source_id,
            created=False,
        )
        assert document.title == "Refund policy"
        assert document.content == "Refunds are available within 30 days."
        assert KnowledgeSource.objects.unscoped().filter(team=self.team, is_generated=True).count() == 1
        assert KnowledgeDocument.objects.unscoped().filter(source_id=first.source_id).count() == 1

    @parameterized.expand(
        [
            ("analysis_version", "conversations", "post_resolution_v2"),
            ("provider", "other_provider", "post_resolution_v1"),
        ]
    )
    def test_new_identity_reuses_team_source(self, _name: str, provider: str, analysis_version: str) -> None:
        first = logic.create_generated_knowledge_document(self._input())
        second = logic.create_generated_knowledge_document(
            self._input(provider=provider, analysis_version=analysis_version)
        )

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

        mine = logic.create_generated_knowledge_document(self._input())
        theirs = logic.create_generated_knowledge_document(self._input(team_id=other_team.id))

        assert mine.source_id != theirs.source_id
        assert mine.id != theirs.id
        assert KnowledgeDocument.objects.unscoped().get(id=mine.id).team_id == self.team.id
        assert KnowledgeDocument.objects.unscoped().get(id=theirs.id).team_id == other_team.id

    def test_child_team_writes_to_canonical_team(self) -> None:
        child_team = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            project=self.team.project,
            name="Child environment",
        )

        result = logic.create_generated_knowledge_document(self._input(team_id=child_team.id))

        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        assert KnowledgeSource.objects.unscoped().get(id=result.source_id).team_id == self.team.id
        assert document.team_id == self.team.id
        assert document.metadata["source_team_id"] == child_team.id

    def test_disabling_generated_source_removes_it_from_search_without_deleting_data(self) -> None:
        result = logic.create_generated_knowledge_document(self._input())
        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        logic.set_document_safety(
            team_id=self.team.id,
            document_id=document.id,
            verdict=SafetyVerdict.SAFE,
            content_hash=document.content_hash,
        )
        assert logic.search_knowledge(self.team.id, "refunds")

        assert logic.set_generated_knowledge_source_ready(self.team.id, ready=False) is True

        assert logic.search_knowledge(self.team.id, "refunds") == []
        assert KnowledgeDocument.objects.unscoped().filter(id=result.id).exists()
        assert KnowledgeChunk.objects.unscoped().filter(document_id=result.id).exists()

    def test_disabling_generated_source_remains_effective_after_later_publish(self) -> None:
        first = logic.create_generated_knowledge_document(self._input())
        assert logic.set_generated_knowledge_source_ready(self.team.id, ready=False) is True

        second = logic.create_generated_knowledge_document(self._input(analysis_version="post_resolution_v2"))

        source = KnowledgeSource.objects.unscoped().get(id=first.source_id)
        assert second.source_id == first.source_id
        assert source.status == SourceStatus.ERROR

    def test_logic_mutations_reject_generated_source(self) -> None:
        result = logic.create_generated_knowledge_document(self._input())

        with self.assertRaises(logic.GeneratedSourceReadOnlyError):
            logic.update_text_source(
                source_id=result.source_id,
                team_id=self.team.id,
                name="Changed",
                text="Changed content",
            )
        with self.assertRaises(logic.GeneratedSourceReadOnlyError):
            logic.delete_source(result.source_id, self.team.id)
        with self.assertRaises(logic.GeneratedSourceReadOnlyError):
            logic.claim_refresh_source(source_id=result.source_id, team_id=self.team.id)

    def test_generated_source_does_not_consume_user_source_quota(self) -> None:
        logic.create_generated_knowledge_document(self._input())

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

    def test_generated_source_can_be_created_at_user_source_quota(self) -> None:
        with patch.object(logic, "MAX_SOURCES_PER_TEAM", 1):
            logic.create_text_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="User source",
                text="User-authored content",
            )

            result = logic.create_generated_knowledge_document(self._input())

        assert KnowledgeSource.objects.unscoped().get(id=result.source_id).is_generated is True

    def test_chunk_quota_failure_rolls_back_new_source(self) -> None:
        with (
            patch.object(logic, "MAX_CHUNKS_PER_TEAM", 0),
            self.assertRaises(logic.QuotaExceededError),
        ):
            logic.create_generated_knowledge_document(self._input())

        assert not KnowledgeSource.objects.unscoped().filter(team=self.team, is_generated=True).exists()

    @parameterized.expand(
        [
            (
                "title",
                "x" * (logic.MAX_GENERATED_DOCUMENT_TITLE_LENGTH + 1),
                "Valid content",
            ),
            (
                "content",
                "Valid title",
                "x" * (logic.MAX_TEXT_SIZE_BYTES + 1),
            ),
        ]
    )
    def test_rejects_unbounded_document_fields(self, _name: str, title: str, content: str) -> None:
        with self.assertRaises(logic.InvalidGeneratedKnowledgeDocument):
            logic.create_generated_knowledge_document(self._input(title=title, content=content))

    @parameterized.expand(
        [
            ("empty", ""),
            ("too_long", "x" * (logic.MAX_ANALYSIS_VERSION_LENGTH + 1)),
            ("invalid_character", "post resolution v1"),
        ]
    )
    def test_rejects_invalid_analysis_version(self, _name: str, analysis_version: str) -> None:
        with self.assertRaises(logic.InvalidGeneratedKnowledgeDocument):
            logic.create_generated_knowledge_document(self._input(analysis_version=analysis_version))

    @parameterized.expand(
        [
            ("empty_provider", "", 42, 1),
            ("uppercase_provider", "Conversations", 42, 1),
            ("too_long_provider", "x" * (logic.MAX_PROVIDER_LENGTH + 1), 42, 1),
            ("zero_ticket_number", "conversations", 0, 1),
            ("zero_source_team", "conversations", 42, 0),
        ]
    )
    def test_rejects_invalid_provenance(
        self, _name: str, provider: str, ticket_number: int, source_team_id: int
    ) -> None:
        with self.assertRaises(logic.InvalidGeneratedKnowledgeDocument):
            logic.create_generated_knowledge_document(
                self._input(provider=provider, ticket_number=ticket_number, source_team_id=source_team_id)
            )

    @parameterized.expand(
        [
            ("ticket_in_title", "10000000-0000-0000-0000-000000000001", "Valid content"),
            ("ticket_in_content", "Valid title", "See ticket 10000000-0000-0000-0000-000000000001."),
            ("ticket_hex_in_content", "Valid title", "See ticket 10000000000000000000000000000001."),
            ("comment_in_title", "20000000-0000-0000-0000-000000000002", "Valid content"),
            ("comment_in_content", "Valid title", "See comment 20000000-0000-0000-0000-000000000002."),
        ]
    )
    def test_rejects_provenance_identifiers_in_searchable_content(
        self,
        _name: str,
        title: str,
        content: str,
    ) -> None:
        with self.assertRaises(logic.InvalidGeneratedKnowledgeDocument):
            logic.create_generated_knowledge_document(self._input(title=title, content=content))
