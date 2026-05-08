import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.business_knowledge.backend.constants import CHUNK_HARD_MAX_CHARS
from products.business_knowledge.backend.logic import (
    QuotaExceededError,
    TextTooLargeError,
    _chunk_id,
    chunk_text,
    create_text_source,
)
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeDocument, SourceStatus


class TestChunker(BaseTest):
    @parameterized.expand(
        [
            ("empty", "", 0),
            ("single_short", "hello", 1),
            ("two_paragraphs", "a\n\nb", 1),
            ("crlf_paragraphs", "a\r\n\r\nb", 1),
            ("whitespace_only", "   \n\n \t\n", 0),
        ]
    )
    def test_basic_chunking(self, _name: str, text: str, expected_count: int) -> None:
        assert len(chunk_text(text)) == expected_count

    def test_chunks_respect_target_size(self) -> None:
        paragraph = ("word " * 100).strip()
        text = "\n\n".join([paragraph] * 20)
        chunks = chunk_text(text)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c.content) <= CHUNK_HARD_MAX_CHARS

    def test_hard_splits_oversized_paragraph(self) -> None:
        # One paragraph larger than the hard cap should be broken up rather
        # than emitted as a single chunk.
        oversized = "x " * (CHUNK_HARD_MAX_CHARS)
        chunks = chunk_text(oversized)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c.content) <= CHUNK_HARD_MAX_CHARS

    def test_ordinals_are_zero_indexed_and_contiguous(self) -> None:
        text = "\n\n".join(f"para-{i}" * 200 for i in range(5))
        chunks = chunk_text(text)
        assert [c.ordinal for c in chunks] == list(range(len(chunks)))

    def test_chunk_ids_are_deterministic(self) -> None:
        source_a = uuid.uuid4()
        source_b = uuid.uuid4()
        a = _chunk_id(source_a, "doc-stable-123", "", 0)
        b = _chunk_id(source_a, "doc-stable-123", "", 0)
        c = _chunk_id(source_a, "doc-stable-123", "", 1)
        d = _chunk_id(source_a, "doc-stable-456", "", 0)
        e = _chunk_id(source_b, "doc-stable-123", "", 0)
        assert a == b
        assert a != c
        assert a != d
        # Different sources with identical document/heading/ordinal → different
        # chunk UUIDs. This is what protects us from IntegrityError when two
        # URL-backed sources crawl the same URL (stable_id == url).
        assert a != e


class TestCreateTextSource(BaseTest):
    def _count_for(self, model, team):
        return model.objects.filter(team=team).count()

    def test_create_text_source_happy_path(self) -> None:
        source = create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Product docs",
            text="Paragraph one.\n\nParagraph two has more detail here.",
        )
        assert source.status == SourceStatus.READY
        assert self._count_for(KnowledgeDocument, self.team) == 1
        assert self._count_for(KnowledgeChunk, self.team) >= 1
        # team_id must land on child rows too.
        assert KnowledgeChunk.objects.filter(team=self.team).count() == KnowledgeChunk.objects.count()
        assert KnowledgeDocument.objects.filter(team=self.team).count() == KnowledgeDocument.objects.count()

    def test_chunks_carry_source_and_document_fks(self) -> None:
        source = create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Docs",
            text="a" * 300 + "\n\n" + "b" * 300,
        )
        chunks = KnowledgeChunk.objects.filter(source=source)
        assert chunks.count() >= 1
        for c in chunks:
            assert c.source_id == source.id
            assert c.document_id is not None
            assert c.char_count == len(c.content)

    def test_text_too_large_rejected(self) -> None:
        # 1 MB + 1 byte over the limit.
        huge = "x" * 1_000_001
        with self.assertRaises(TextTooLargeError):
            create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Huge", text=huge)

    def test_quota_on_source_count(self) -> None:
        # Patch the cap so the test finishes in one source instead of 500.
        with patch("products.business_knowledge.backend.logic.MAX_SOURCES_PER_TEAM", 1):
            create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="First", text="hello")
            with self.assertRaises(QuotaExceededError):
                create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Second", text="hello")

    def test_cross_team_isolation(self) -> None:
        # Another team in the same org should not be able to read or list
        # rows we create.
        from posthog.models.team import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Mine", text="secret content")
        from products.business_knowledge.backend import logic

        assert len(logic.list_for_team(self.team.id)) == 1
        assert len(logic.list_for_team(other_team.id)) == 0
