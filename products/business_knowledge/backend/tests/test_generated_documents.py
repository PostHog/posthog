import uuid
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog, Trigger
from posthog.models.activity_logging.model_activity import ActivityTriggerContext
from posthog.models.scoping import team_scope
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

_EVIDENCE_REVISION_AT = datetime(2026, 1, 1, tzinfo=UTC)


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
        evidence_revision_at: datetime = _EVIDENCE_REVISION_AT,
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
            evidence_revision_at=evidence_revision_at,
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
            logic.EVIDENCE_REVISION_AT_KEY: input.evidence_revision_at.isoformat(),
        }

        assert result.created is True
        assert source.team_id == self.team.id
        assert source.name == "Refund policy"
        assert source.id == logic.learned_source_id_for(
            team_id=self.team.id,
            provider=input.provider,
            ticket_id=input.ticket_id,
            resolution_comment_id=input.resolution_comment_id,
            analysis_version=input.analysis_version,
        )
        assert source.source_type == SourceType.TEXT
        assert source.is_generated is True
        assert source.status == SourceStatus.READY
        assert source.created_by_id is None
        assert document.safety_verdict == SafetyVerdict.UNKNOWN
        assert document.metadata == {"source_type": SourceType.TEXT, **provenance}
        assert chunks
        assert logic.search_knowledge(self.team.id, "refunds") == []
        assert logic.get_source_text_for_team(result.source_id, self.team.id) == input.content

        searchable_text = "\n".join(
            [source.name, document.stable_id, document.title, document.content, *(chunk.content for chunk in chunks)]
        )
        assert str(input.ticket_id) not in searchable_text
        assert str(input.resolution_comment_id) not in searchable_text
        assert input.analysis_version not in searchable_text

    def test_get_chunks_by_ids_round_trips_is_generated(self) -> None:
        generated = logic.create_generated_knowledge_document(self._input())
        text_source = logic.create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Manual notes",
            text="Install the SDK from Project settings.",
        )
        KnowledgeDocument.objects.unscoped().filter(id__in=[generated.id]).update(safety_verdict=SafetyVerdict.SAFE)
        KnowledgeDocument.objects.unscoped().filter(source_id=text_source.id).update(safety_verdict=SafetyVerdict.SAFE)

        generated_chunk_id = (
            KnowledgeChunk.objects.unscoped().filter(document_id=generated.id).values_list("id", flat=True)[0]
        )
        text_chunk_id = (
            KnowledgeChunk.objects.unscoped().filter(source_id=text_source.id).values_list("id", flat=True)[0]
        )

        results = {
            row.chunk_id: row.is_generated
            for row in logic.get_chunks_by_ids(self.team.id, [generated_chunk_id, text_chunk_id])
        }
        assert results[generated_chunk_id] is True
        assert results[text_chunk_id] is False

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
    def test_new_identity_creates_a_new_source(self, _name: str, provider: str, analysis_version: str) -> None:
        first = logic.create_generated_knowledge_document(self._input())
        second = logic.create_generated_knowledge_document(
            self._input(provider=provider, analysis_version=analysis_version)
        )

        assert first.source_id != second.source_id
        assert first.id != second.id
        assert KnowledgeSource.objects.unscoped().filter(team=self.team, is_generated=True).count() == 2
        assert KnowledgeDocument.objects.unscoped().filter(source_id=first.source_id).count() == 1
        assert KnowledgeDocument.objects.unscoped().filter(source_id=second.source_id).count() == 1

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

        logic.update_text_source(
            source_id=result.source_id,
            team_id=self.team.id,
            name="Refund policy",
            text="Changed refund window.",
        )
        document.refresh_from_db()
        logic.set_document_safety(
            team_id=self.team.id,
            document_id=document.id,
            verdict=SafetyVerdict.SAFE,
            content_hash=document.content_hash,
        )
        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        assert source.status == SourceStatus.ERROR
        assert source.error_message == logic.GENERATED_SOURCE_DISABLED_MESSAGE
        assert logic.search_knowledge(self.team.id, "refunds") == []

    def test_disabling_generated_source_remains_effective_after_later_publish(self) -> None:
        first = logic.create_generated_knowledge_document(self._input())
        assert logic.set_generated_knowledge_source_ready(self.team.id, ready=False) is True

        second = logic.create_generated_knowledge_document(self._input(analysis_version="post_resolution_v2"))

        first_source = KnowledgeSource.objects.unscoped().get(id=first.source_id)
        second_source = KnowledgeSource.objects.unscoped().get(id=second.source_id)
        assert second.source_id != first.source_id
        assert first_source.status == SourceStatus.ERROR
        assert second_source.status == SourceStatus.ERROR
        assert second_source.error_message == logic.GENERATED_SOURCE_DISABLED_MESSAGE

    def test_generated_text_source_allows_edit_and_delete_but_not_refresh(self) -> None:
        result = logic.create_generated_knowledge_document(self._input())

        renamed_first = logic.update_text_source(
            source_id=result.source_id,
            team_id=self.team.id,
            name="Renamed policy",
            text=None,
        )
        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        assert renamed_first is not None
        assert renamed_first.name == "Renamed policy"
        assert document.title == "Renamed policy"
        assert document.content == "Refunds are available within 30 days."
        assert document.metadata["edited_by_user"] is True
        assert document.metadata["ticket_number"] == 42

        updated = logic.update_text_source(
            source_id=result.source_id,
            team_id=self.team.id,
            name="Refund policy",
            text="Changed content",
        )
        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        chunks = list(KnowledgeChunk.objects.unscoped().filter(document=document))

        assert updated is not None
        assert document.id == result.id
        assert document.content == "Changed content"
        assert document.safety_verdict == SafetyVerdict.UNKNOWN
        assert document.metadata["edited_by_user"] is True
        assert document.metadata["ticket_number"] == 42
        assert chunks
        assert chunks[0].content == "Changed content"

        renamed = logic.update_text_source(
            source_id=result.source_id,
            team_id=self.team.id,
            name="Renamed policy",
            text=None,
        )
        document.refresh_from_db()
        assert renamed is not None
        assert renamed.name == "Renamed policy"
        assert document.title == "Renamed policy"
        assert document.content == "Changed content"

        with self.assertRaises(logic.GeneratedSourceReadOnlyError):
            logic.claim_refresh_source(source_id=result.source_id, team_id=self.team.id)

        assert logic.delete_source(result.source_id, self.team.id) is True
        assert not KnowledgeSource.objects.unscoped().filter(id=result.source_id).exists()

    def test_generated_source_with_multiple_documents_cannot_be_edited(self) -> None:
        result = logic.create_generated_knowledge_document(self._input())
        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        extra_id = uuid.uuid4()
        KnowledgeDocument.objects.unscoped().create(
            id=extra_id,
            team_id=self.team.id,
            source=source,
            stable_id=str(extra_id),
            title="Second topic",
            content="Second topic body.",
            content_hash="abc",
        )
        first = KnowledgeDocument.objects.unscoped().get(id=result.id)
        original_chunks = list(
            KnowledgeChunk.objects.unscoped().filter(document_id=result.id).values_list("id", "content")
        )

        with self.assertRaises(logic.GeneratedSourceHasMultipleDocuments):
            logic.get_source_text_for_team(result.source_id, self.team.id)
        with self.assertRaises(logic.GeneratedSourceHasMultipleDocuments):
            logic.update_text_source(
                source_id=result.source_id,
                team_id=self.team.id,
                name="Refund policy",
                text="Joined text that must not replace both documents.",
            )
        with self.assertRaises(logic.GeneratedSourceHasMultipleDocuments):
            logic.update_text_source(
                source_id=result.source_id,
                team_id=self.team.id,
                name="Renamed",
                text=None,
            )

        first.refresh_from_db()
        extra = KnowledgeDocument.objects.unscoped().get(id=extra_id)
        assert KnowledgeDocument.objects.unscoped().filter(source_id=result.source_id).count() == 2
        assert first.content == "Refunds are available within 30 days."
        assert extra.content == "Second topic body."
        assert extra.metadata.get("edited_by_user") is not True
        assert (
            list(KnowledgeChunk.objects.unscoped().filter(document_id=result.id).values_list("id", "content"))
            == original_chunks
        )

    def test_user_edit_survives_a_retry_of_the_same_identity(self) -> None:
        first = logic.create_generated_knowledge_document(self._input())
        logic.update_text_source(
            source_id=first.source_id,
            team_id=self.team.id,
            name="Refund policy",
            text="Edited by a person.",
        )

        retry = logic.create_generated_knowledge_document(
            self._input(content="Analyzer rewrite that must not replace the edit.")
        )
        document = KnowledgeDocument.objects.unscoped().get(id=first.id)

        assert retry == logic.GeneratedKnowledgeDocument(
            id=first.id,
            source_id=first.source_id,
            created=False,
        )
        assert document.content == "Edited by a person."
        assert document.metadata["edited_by_user"] is True

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

    def test_long_title_truncates_source_name(self) -> None:
        title = "T" * 300
        result = logic.create_generated_knowledge_document(self._input(title=title))

        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        assert source.name == title[: logic.MAX_GENERATED_SOURCE_NAME_LENGTH]
        assert document.title == title[: logic.MAX_GENERATED_SOURCE_NAME_LENGTH]

    _REPLACEMENT_TICKET_ID = uuid.UUID("10000000-0000-0000-0000-000000000099")

    def _searchable_generated_source(self) -> tuple[logic.GeneratedKnowledgeDocument, KnowledgeDocument]:
        result = logic.create_generated_knowledge_document(self._input())
        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        logic.set_document_safety(
            team_id=self.team.id,
            document_id=document.id,
            verdict=SafetyVerdict.SAFE,
            content_hash=document.content_hash,
        )
        return result, document

    def _supersede(
        self,
        source_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        replacement_source_id: uuid.UUID | None = None,
    ) -> logic.KnowledgeSourceSupersession:
        return logic.supersede_knowledge_source(
            team_id=self.team.id,
            source_id=source_id,
            document_id=document_id,
            superseded_by_ticket_id=self._REPLACEMENT_TICKET_ID,
            superseded_by_ticket_number=99,
            superseded_by_source_id=replacement_source_id,
        )

    def test_supersede_disables_the_source_and_records_where_the_newer_answer_came_from(self) -> None:
        result, document = self._searchable_generated_source()
        replacement_id = uuid.uuid4()
        assert logic.search_knowledge(self.team.id, "refunds")

        with ActivityTriggerContext(
            Trigger(job_type="business-knowledge-learn", job_id="run-1", payload={"ticket_number": 99})
        ):
            supersession = self._supersede(result.source_id, document.id, replacement_source_id=replacement_id)

        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        document.refresh_from_db()
        provenance = document.metadata or {}
        activity = ActivityLog.objects.filter(
            scope="KnowledgeSource", item_id=str(result.source_id), activity="updated"
        ).latest("created_at")
        assert supersession.applied is True
        assert supersession.previous_ticket_number == 42
        assert source.status == SourceStatus.ERROR
        assert source.error_message == logic.SUPERSEDED_SOURCE_MESSAGE
        assert document.content == "Refunds are available within 30 days."
        assert provenance["superseded_by_ticket_id"] == str(self._REPLACEMENT_TICKET_ID)
        assert provenance["superseded_by_ticket_number"] == 99
        assert provenance["superseded_by_source_id"] == str(replacement_id)
        assert logic.search_knowledge(self.team.id, "refunds") == []
        assert (activity.detail or {})["trigger"]["job_type"] == "business-knowledge-learn"

    def test_supersede_refuses_a_source_a_person_wrote(self) -> None:
        source = logic.create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Refund policy",
            text="Refunds are available within 30 days.",
        )
        document = KnowledgeDocument.objects.unscoped().get(source_id=source.id)

        supersession = self._supersede(source.id, document.id)

        source.refresh_from_db()
        assert supersession.outcome == "source_not_generated"
        assert source.status == SourceStatus.READY
        assert source.error_message == ""

    def test_supersede_is_a_no_op_when_the_replacement_is_the_source_itself(self) -> None:
        result, document = self._searchable_generated_source()

        supersession = self._supersede(result.source_id, document.id, replacement_source_id=result.source_id)

        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        assert supersession.outcome == "same_source"
        assert source.status == SourceStatus.READY
        assert logic.search_knowledge(self.team.id, "refunds")

    def test_supersede_leaves_another_teams_source_alone(self) -> None:
        other_team = Team.objects.create_with_data(
            organization=self.organization,
            initiating_user=self.user,
            name="Other",
        )
        theirs = logic.create_generated_knowledge_document(self._input(team_id=other_team.id))

        supersession = self._supersede(theirs.source_id, theirs.id)

        assert supersession.outcome == "nothing_to_supersede"
        assert KnowledgeSource.objects.unscoped().get(id=theirs.source_id).status == SourceStatus.READY

    def test_superseded_source_stays_out_of_search_after_an_edit(self) -> None:
        result, document = self._searchable_generated_source()
        self._supersede(result.source_id, document.id)

        logic.update_text_source(
            source_id=result.source_id,
            team_id=self.team.id,
            name="Refund policy",
            text="Refunds are available within 30 days. Updated.",
        )
        document.refresh_from_db()
        logic.set_document_safety(
            team_id=self.team.id,
            document_id=document.id,
            verdict=SafetyVerdict.SAFE,
            content_hash=document.content_hash,
        )

        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        assert source.status == SourceStatus.ERROR
        assert source.error_message == logic.SUPERSEDED_SOURCE_MESSAGE
        assert logic.search_knowledge(self.team.id, "refunds") == []

    def test_superseded_source_stays_out_of_search_when_learning_is_turned_off_and_on(self) -> None:
        result, document = self._searchable_generated_source()
        self._supersede(result.source_id, document.id)

        logic.set_generated_knowledge_source_ready(self.team.id, ready=False)
        logic.set_generated_knowledge_source_ready(self.team.id, ready=True)

        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        assert source.error_message == logic.SUPERSEDED_SOURCE_MESSAGE
        assert logic.search_knowledge(self.team.id, "refunds") == []

    @parameterized.expand(
        [
            ("restored_by_a_person", True, "applied"),
            ("still_superseded", False, "already_superseded"),
        ]
    )
    def test_supersede_repeats_only_after_a_person_restores_the_source(
        self, _name: str, restore: bool, expected_outcome: str
    ) -> None:
        result, document = self._searchable_generated_source()
        self._supersede(result.source_id, document.id)
        if restore:
            with team_scope(self.team.id, canonical=True):
                KnowledgeSource.objects.filter(id=result.source_id).update(status=SourceStatus.READY, error_message="")
            assert logic.search_knowledge(self.team.id, "refunds")

        repeat = self._supersede(result.source_id, document.id)

        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        assert repeat.outcome == expected_outcome
        assert source.status == SourceStatus.ERROR
        assert source.error_message == logic.SUPERSEDED_SOURCE_MESSAGE
        assert logic.search_knowledge(self.team.id, "refunds") == []

    def test_supersede_leaves_a_source_that_holds_other_documents(self) -> None:
        result = logic.create_generated_knowledge_document(self._input())
        document = KnowledgeDocument.objects.unscoped().get(id=result.id)
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.create(
                team_id=self.team.id,
                source_id=result.source_id,
                stable_id="second-page",
                title="Shipping policy",
                content="Orders ship within two days.",
                safety_verdict=SafetyVerdict.SAFE,
            )

        supersession = logic.supersede_knowledge_source(
            team_id=self.team.id,
            source_id=result.source_id,
            document_id=document.id,
            superseded_by_ticket_id=uuid.uuid4(),
            superseded_by_ticket_number=99,
        )

        source = KnowledgeSource.objects.unscoped().get(id=result.source_id)
        assert supersession.outcome == "source_has_other_documents"
        assert source.status == SourceStatus.READY
        assert source.error_message == ""

    def test_learned_source_cap_blocks_new_identities_not_retries(self) -> None:
        first = logic.create_generated_knowledge_document(self._input())

        with patch.object(logic, "MAX_LEARNED_SOURCES_PER_TEAM", 1):
            retry = logic.create_generated_knowledge_document(self._input(content="Retry must skip the cap."))
            with self.assertRaises(logic.LearnedSourceCapReached):
                logic.create_generated_knowledge_document(self._input(analysis_version="post_resolution_v2"))

        assert retry.source_id == first.source_id
        assert KnowledgeSource.objects.unscoped().filter(team=self.team, is_generated=True).count() == 1
