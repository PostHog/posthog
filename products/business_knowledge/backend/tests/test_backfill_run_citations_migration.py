from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

from posthog.test.base import BaseTest

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from posthog.models import Organization, Team
from posthog.models.comment import Comment
from posthog.models.scoping import team_scope

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeRunCitation

MIGRATION = "0029_backfill_knowledge_run_citations"


class TestBackfillRunCitationsMigration(BaseTest):
    def _chunk(self, team: Team) -> KnowledgeChunk:
        source = logic.create_text_source(
            team_id=team.id, created_by_id=self.user.id, name="Refunds", text="Refunds take five days."
        )
        with team_scope(team.id, canonical=True):
            return KnowledgeChunk.objects.get(source_id=source.id)

    def _note(self, *, author_type: str, citations: list[str], ticket_id: str) -> Comment:
        return Comment.objects.create(
            team_id=self.team.id,
            scope="conversations_ticket",
            item_id=ticket_id,
            content="Refunds take five days.",
            item_context={"author_type": author_type, "citations": citations, "confidence": 0.7},
        )

    def test_backfill_records_only_ai_notes_and_only_the_teams_own_chunks(self) -> None:
        chunk = self._chunk(self.team)
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        foreign_chunk = self._chunk(other_team)
        ticket_id = uuid4()
        written_at = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        ai_note = self._note(
            author_type="AI",
            citations=[str(chunk.id), str(foreign_chunk.id), "https://example.com/docs/refunds"],
            ticket_id=str(ticket_id),
        )
        Comment.objects.filter(id=ai_note.id).update(created_at=written_at)
        self._note(author_type="support", citations=[str(chunk.id)], ticket_id=str(ticket_id))

        historical_apps = MigrationLoader(connection).project_state(("business_knowledge", MIGRATION)).apps
        backfill = import_module(f"products.business_knowledge.backend.migrations.{MIGRATION}").backfill_run_citations
        with connection.schema_editor() as schema_editor:
            for _attempt in range(2):
                backfill(historical_apps, schema_editor)

        rows = list(
            KnowledgeRunCitation.objects.unscoped().values_list(
                "team_id", "run_id", "ticket_id", "chunk_id", "source_id", "confidence", "created_at"
            )
        )
        assert rows == [(self.team.id, f"note:{ai_note.id}", ticket_id, chunk.id, chunk.source_id, 0.7, written_at)]
