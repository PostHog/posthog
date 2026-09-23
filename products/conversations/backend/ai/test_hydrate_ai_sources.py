import uuid
import datetime

from posthog.test.base import BaseTest

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.models import KnowledgeChunk
from products.conversations.backend.ai.evidence import hydrate_ai_sources

_EVIDENCE_REVISION_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


class TestHydrateAiSources(BaseTest):
    def test_learned_unknown_chunks_still_hydrate(self) -> None:
        generated = logic.create_generated_knowledge_document(
            logic.CreateGeneratedKnowledgeDocument(
                team_id=self.team.id,
                provider="conversations",
                ticket_id=uuid.UUID("10000000-0000-0000-0000-000000000001"),
                ticket_number=42,
                source_team_id=self.team.id,
                resolution_comment_id=uuid.UUID("20000000-0000-0000-0000-000000000002"),
                analysis_version="post_resolution_v1",
                title="Refund policy",
                content="Refunds are available within 30 days.",
                evidence_revision_at=_EVIDENCE_REVISION_AT,
            )
        )
        chunk_id = KnowledgeChunk.objects.unscoped().filter(document_id=generated.id).values_list("id", flat=True)[0]

        sources = hydrate_ai_sources(team_id=self.team.id, citations=[str(chunk_id)])

        assert len(sources) == 1
        assert sources[0].is_generated is True
        assert sources[0].learned_from_ticket_number == 42
        assert sources[0].source_id == str(generated.source_id)
        assert sources[0].title == "Refund policy"
        assert sources[0].url is None

    def test_preserves_citation_order_across_urls_and_chunks(self) -> None:
        text_source = logic.create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Manual notes",
            text="Install the SDK from Project settings.",
        )
        chunk_id = KnowledgeChunk.objects.unscoped().filter(source_id=text_source.id).values_list("id", flat=True)[0]
        url = "https://example.com/docs/sdk"

        sources = hydrate_ai_sources(team_id=self.team.id, citations=[url, str(chunk_id)])

        assert [source.ref for source in sources] == [url, str(chunk_id)]
        assert sources[0].url == url
        assert sources[1].source_id == str(text_source.id)
        assert sources[1].is_generated is False
