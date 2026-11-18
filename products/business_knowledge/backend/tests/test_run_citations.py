from uuid import uuid4

from posthog.test.base import BaseTest

from posthog.models.scoping import team_scope

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.facade.api import record_run_citations
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeRunCitation


class TestRunCitations(BaseTest):
    def _chunk(self) -> KnowledgeChunk:
        source = logic.create_text_source(
            team_id=self.team.id, created_by_id=self.user.id, name="Refunds", text="Refunds take five days."
        )
        with team_scope(self.team.id, canonical=True):
            return KnowledgeChunk.objects.get(source_id=source.id)

    def _rows(self) -> list[KnowledgeRunCitation]:
        with team_scope(self.team.id, canonical=True):
            return list(KnowledgeRunCitation.objects.all())

    def test_records_one_row_per_cited_chunk_once_per_run(self) -> None:
        chunk = self._chunk()
        ticket_id = uuid4()
        citations = [str(chunk.id), "https://example.com/docs/refunds", str(uuid4()), str(chunk.id)]

        for _attempt in range(2):
            record_run_citations(
                team_id=self.team.id,
                run_id="run-1",
                ticket_id=ticket_id,
                citations=citations,
                persist_as="findings",
                confidence=0.8,
            )
        record_run_citations(team_id=self.team.id, run_id="run-2", ticket_id=ticket_id, citations=citations)
        record_run_citations(team_id=self.team.id, run_id="r" * 500, ticket_id=ticket_id, citations=citations)

        assert sorted(
            (row.run_id, row.chunk_id, row.document_id, row.source_id, row.persist_as, row.confidence)
            for row in self._rows()
        ) == [
            ("run-1", chunk.id, chunk.document_id, chunk.source_id, "findings", 0.8),
            ("run-2", chunk.id, chunk.document_id, chunk.source_id, "", None),
        ]
