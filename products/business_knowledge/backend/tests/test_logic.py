import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.business_knowledge.backend.constants import CHUNK_HARD_MAX_CHARS, MAX_ALWAYS_ON_CONTEXT_CHARS
from products.business_knowledge.backend.logic import (
    QuotaExceededError,
    TextTooLargeError,
    _chunk_id,
    chunk_text,
    create_text_source,
    get_always_on_context,
)
from products.business_knowledge.backend.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SafetyVerdict,
    SourceStatus,
)


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
        return model.objects.unscoped().filter(team=team).count()

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
        assert (
            KnowledgeChunk.objects.unscoped().filter(team=self.team).count()
            == KnowledgeChunk.objects.unscoped().count()
        )
        assert (
            KnowledgeDocument.objects.unscoped().filter(team=self.team).count()
            == KnowledgeDocument.objects.unscoped().count()
        )

    def test_chunks_carry_source_and_document_fks(self) -> None:
        source = create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Docs",
            text="a" * 300 + "\n\n" + "b" * 300,
        )
        chunks = KnowledgeChunk.objects.unscoped().filter(source=source)
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


class TestGetAlwaysOnContext(BaseTest):
    def _create_source(
        self, *, always_include: bool = False, status: str = SourceStatus.READY, safe: bool = True
    ) -> KnowledgeSource:
        source = KnowledgeSource.objects.unscoped().create(
            team_id=self.team.id,
            name="test",
            source_type="text",
            status=status,
            always_include=always_include,
        )
        doc = KnowledgeDocument.objects.unscoped().create(
            team_id=self.team.id,
            source=source,
            stable_id=str(uuid.uuid4()),
            title="doc",
            content="chunk content here",
            content_hash="abc",
            safety_verdict=SafetyVerdict.SAFE if safe else SafetyVerdict.UNKNOWN,
        )
        KnowledgeChunk.objects.unscoped().create(
            id=uuid.uuid4(),
            team_id=self.team.id,
            source=source,
            document=doc,
            ordinal=0,
            content="chunk content here",
            char_count=18,
        )
        return source

    def test_returns_chunks_from_always_include_sources(self) -> None:
        self._create_source(always_include=True)
        self._create_source(always_include=False)
        results = get_always_on_context(self.team.id)
        assert len(results) == 1
        assert results[0].content == "chunk content here"

    def test_excludes_unsafe_documents(self) -> None:
        self._create_source(always_include=True, safe=False)
        results = get_always_on_context(self.team.id)
        assert len(results) == 0

    def test_excludes_non_ready_sources(self) -> None:
        self._create_source(always_include=True, status=SourceStatus.PROCESSING)
        results = get_always_on_context(self.team.id)
        assert len(results) == 0

    def test_respects_char_cap(self) -> None:
        source = KnowledgeSource.objects.unscoped().create(
            team_id=self.team.id,
            name="big",
            source_type="text",
            status=SourceStatus.READY,
            always_include=True,
        )
        doc = KnowledgeDocument.objects.unscoped().create(
            team_id=self.team.id,
            source=source,
            stable_id=str(uuid.uuid4()),
            title="big doc",
            content="x",
            content_hash="def",
            safety_verdict=SafetyVerdict.SAFE,
        )
        # Create chunks that together exceed the cap
        chunk_size = MAX_ALWAYS_ON_CONTEXT_CHARS // 2 + 1
        for i in range(3):
            KnowledgeChunk.objects.unscoped().create(
                id=uuid.uuid4(),
                team_id=self.team.id,
                source=source,
                document=doc,
                ordinal=i,
                content="x" * chunk_size,
                char_count=chunk_size,
            )
        results = get_always_on_context(self.team.id)
        total = sum(len(r.content) for r in results)
        assert total <= MAX_ALWAYS_ON_CONTEXT_CHARS
        # Should have gotten at most 1 chunk (2nd would exceed cap)
        assert len(results) == 1
