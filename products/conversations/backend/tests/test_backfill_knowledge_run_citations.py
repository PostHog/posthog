from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import BaseTest

from posthog.models.comment import Comment
from posthog.models.scoping import team_scope

from products.business_knowledge.backend import logic as knowledge_logic
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeRunCitation
from products.conversations.backend.management.commands.backfill_knowledge_run_citations import backfill_run_citations


class TestBackfillKnowledgeRunCitations(BaseTest):
    def test_backfill_records_each_ai_note_as_one_run_at_the_time_it_was_written(self) -> None:
        source = knowledge_logic.create_text_source(
            team_id=self.team.id, created_by_id=self.user.id, name="Refunds", text="Refunds take five days."
        )
        with team_scope(self.team.id, canonical=True):
            chunk = KnowledgeChunk.objects.get(source_id=source.id)
        ticket_id = uuid4()
        written_at = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        note = Comment.objects.create(
            team_id=self.team.id,
            scope="conversations_ticket",
            item_id=str(ticket_id),
            content="Refunds take five days.",
            item_context={"author_type": "AI", "citations": [str(chunk.id)], "confidence": 0.7, "persist_as": "reply"},
        )
        Comment.objects.filter(id=note.id).update(created_at=written_at)
        Comment.objects.create(
            team_id=self.team.id,
            scope="conversations_ticket",
            item_id=str(ticket_id),
            content="A human reply.",
            item_context={"author_type": "support", "citations": [str(chunk.id)]},
        )

        for _attempt in range(2):
            backfill_run_citations(team_id=self.team.id)

        with team_scope(self.team.id, canonical=True):
            rows = list(
                KnowledgeRunCitation.objects.values_list("run_id", "ticket_id", "source_id", "confidence", "created_at")
            )
        assert rows == [(f"note:{note.id}", ticket_id, source.id, 0.7, written_at)]
