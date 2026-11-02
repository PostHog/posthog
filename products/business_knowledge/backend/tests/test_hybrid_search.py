import uuid
from uuid import UUID

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.constants import BK_DRILLDOWN_MAX_RADIUS, BK_RRF_SCORE_FLOOR
from products.business_knowledge.backend.libraries import create_library
from products.business_knowledge.backend.llm_telemetry import RetrievalTrace
from products.business_knowledge.backend.logic import (
    _rrf_fuse,
    _semantic_chunk_candidates,
    _SemanticCandidate,
    get_document_window,
    search_knowledge,
    search_knowledge_for_team,
)
from products.business_knowledge.backend.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeLibrarySource,
    KnowledgeSource,
    SafetyVerdict,
    SourceStatus,
)


class TestRRFFusion(SimpleTestCase):
    def test_fts_only_produces_ranked_output(self) -> None:
        ids = [uuid.uuid4() for _ in range(3)]
        fused = _rrf_fuse(ids, [])
        assert fused == ids

    def test_semantic_only_produces_ranked_output(self) -> None:
        candidates = [_SemanticCandidate(chunk_id=uuid.uuid4(), distance=0.1 * i) for i in range(1, 4)]
        fused = _rrf_fuse([], candidates)
        assert fused == [c.chunk_id for c in candidates]

    def test_overlapping_ids_get_higher_score(self) -> None:
        shared_id = uuid.uuid4()
        fts_only = uuid.uuid4()
        sem_only = uuid.uuid4()

        fts_ids = [shared_id, fts_only]
        sem_candidates = [
            _SemanticCandidate(chunk_id=shared_id, distance=0.2),
            _SemanticCandidate(chunk_id=sem_only, distance=0.3),
        ]
        fused = _rrf_fuse(fts_ids, sem_candidates)
        # shared_id appears in both lists so it should rank first
        assert fused[0] == shared_id

    def test_score_floor_filters_low_ranked_semantic_only(self) -> None:
        # A semantic-only candidate ranked very low (rank 1000) scores below the
        # floor and is dropped.
        far_away_id = uuid.uuid4()
        candidates = [_SemanticCandidate(chunk_id=uuid.uuid4(), distance=0.001 * i) for i in range(999)]
        candidates.append(_SemanticCandidate(chunk_id=far_away_id, distance=0.64))
        fused = _rrf_fuse([], candidates, score_floor=BK_RRF_SCORE_FLOOR)
        assert far_away_id not in fused

    def test_fts_anchors_bypass_floor(self) -> None:
        # FTS anchors are real lexical matches and must never be floored out,
        # even deep in the list — otherwise hybrid mode silently returns fewer
        # results than keyword-only mode.
        deep_fts_id = uuid.uuid4()
        fts_ids = [uuid.uuid4() for _ in range(50)] + [deep_fts_id]
        fused = _rrf_fuse(fts_ids, [], score_floor=BK_RRF_SCORE_FLOOR)
        assert deep_fts_id in fused
        assert fused == fts_ids

    def test_duplicate_semantic_candidates_do_not_double_count(self) -> None:
        # A chunk_id repeated in the CH result (un-deduped ReplacingMergeTree)
        # must not accumulate score and leapfrog a genuinely closer single hit.
        dup_id = uuid.uuid4()
        single_id = uuid.uuid4()
        candidates = [
            _SemanticCandidate(chunk_id=single_id, distance=0.1),
            _SemanticCandidate(chunk_id=dup_id, distance=0.2),
            _SemanticCandidate(chunk_id=dup_id, distance=0.25),
        ]
        fused = _rrf_fuse([], candidates)
        # single_id (rank 1) stays ahead of the deduped dup_id (rank 2)
        assert fused == [single_id, dup_id]

    def test_empty_inputs_returns_empty(self) -> None:
        assert _rrf_fuse([], []) == []


class TestHybridSearch(BaseTest):
    """Integration tests for the hybrid (semantic + FTS) search path."""

    def _ready_source_with_chunks(self, texts: list[str], name: str = "src") -> KnowledgeSource:
        source = logic.create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name=name,
            text="\n\n".join(texts),
        )
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
        return source

    def _get_chunk_ids(self, source: KnowledgeSource) -> list[UUID]:
        with team_scope(self.team.id, canonical=True):
            return list(
                KnowledgeChunk.objects.filter(source_id=source.id).order_by("ordinal").values_list("id", flat=True)
            )

    def test_search_result_includes_document_url(self) -> None:
        source = self._ready_source_with_chunks(["The refund policy states thirty day returns."])
        page = "https://example.com/docs/refunds"
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(url=page)
            KnowledgeSource.objects.filter(id=source.id).update(always_include=True)
            chunk_id = KnowledgeChunk.objects.filter(source_id=source.id, ordinal=0).values_list("id", flat=True).get()
            document_id = KnowledgeDocument.objects.filter(source_id=source.id).values_list("id", flat=True).get()

        with self.assertNumQueries(2):
            results = search_knowledge(self.team.id, "refund policy", use_semantic=False)
        assert results[0].url == page

        with self.assertNumQueries(1):
            window = get_document_window(self.team.id, document_id, results[0].ordinal)
        assert window[0].url == page

        with self.assertNumQueries(1):
            hydrated = logic.get_chunks_by_ids(self.team.id, [chunk_id])
        assert hydrated[0].url == page

        with self.assertNumQueries(1):
            always_on = logic.get_always_on_context(self.team.id)
        assert always_on[0].url == page

    def test_use_semantic_false_is_pure_fts(self) -> None:
        self._ready_source_with_chunks(["The refund policy states thirty day returns."])
        results_kw = search_knowledge(self.team.id, "refund policy", use_semantic=False)
        assert len(results_kw) >= 1
        assert any("refund" in r.content.lower() for r in results_kw)

    @patch("products.business_knowledge.backend.logic._semantic_chunk_candidates")
    def test_semantic_candidates_merged_with_fts(self, mock_semantic: MagicMock) -> None:
        # Two separate sources so each yields its own chunk (short texts in one
        # source would collapse into a single chunk under CHUNK_TARGET_CHARS).
        src_refund = self._ready_source_with_chunks(["The refund policy states thirty day returns."], name="refund")
        src_warranty = self._ready_source_with_chunks(["Warranty covers manufacturing defects only."], name="warranty")
        refund_id = self._get_chunk_ids(src_refund)[0]
        warranty_id = self._get_chunk_ids(src_warranty)[0]
        # Semantic returns the warranty chunk, which FTS for "refund" wouldn't match
        mock_semantic.return_value = [_SemanticCandidate(chunk_id=warranty_id, distance=0.3)]

        results = search_knowledge(
            self.team.id,
            "refund policy",
            use_semantic=True,
            query_embedding=[0.1] * 10,
        )
        result_ids = {r.chunk_id for r in results}
        # FTS hit (refund chunk) and semantic-only hit (warranty chunk) both surface
        assert refund_id in result_ids
        assert warranty_id in result_ids

    @patch("products.business_knowledge.backend.logic._semantic_chunk_candidates")
    def test_off_topic_returns_empty(self, mock_semantic: MagicMock) -> None:
        self._ready_source_with_chunks(["The refund policy states thirty day returns."])
        # Semantic returns nothing (all above cutoff)
        mock_semantic.return_value = []

        results = search_knowledge(
            self.team.id,
            "quantum physics experiments",
            use_semantic=True,
            query_embedding=[0.1] * 10,
        )
        # FTS also finds nothing for "quantum physics experiments" so result is empty
        assert results == []

    def _file_source(self, library_id: UUID, source_id: UUID) -> None:
        with team_scope(self.team.id, canonical=True):
            KnowledgeLibrarySource.objects.create(team_id=self.team.id, library_id=library_id, source_id=source_id)

    def test_a_source_in_two_libraries_is_returned_once_for_either(self) -> None:
        source = self._ready_source_with_chunks(["The refund policy states thirty day returns."], name="refund")
        other = self._ready_source_with_chunks(["Warranty covers manufacturing defects only."], name="warranty")
        docs = create_library(self.team.id, "Docs")
        support = create_library(self.team.id, "Support")
        self._file_source(docs.id, source.id)
        self._file_source(support.id, source.id)

        for library_id in (docs.id, support.id):
            results = search_knowledge(self.team.id, "refund policy", use_semantic=False, library_id=library_id)
            names = [result.source_name for result in results]
            assert names.count("refund") == 1
            assert "warranty" not in names
        assert other.name == "warranty"

    def test_an_unfiled_source_is_absent_from_library_search(self) -> None:
        self._ready_source_with_chunks(["The refund policy states thirty day returns."], name="unfiled")
        filed = self._ready_source_with_chunks(["Warranty covers manufacturing defects only."], name="filed")
        library = create_library(self.team.id, "Docs")
        self._file_source(library.id, filed.id)

        scoped = search_knowledge(self.team.id, "refund warranty", use_semantic=False, library_id=library.id)
        unscoped = search_knowledge(self.team.id, "refund warranty", use_semantic=False)
        assert {result.source_name for result in scoped} == {"filed"}
        assert {result.source_name for result in unscoped} == {"unfiled", "filed"}

    @patch("products.business_knowledge.backend.logic.generate_embedding", side_effect=RuntimeError("no gateway"))
    def test_a_child_environment_searches_the_parent_library(self, _embed: MagicMock) -> None:
        child = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            project=self.team.project,
            name="Child environment",
        )
        self._ready_source_with_chunks(["The refund policy states thirty day returns."], name="unfiled")
        filed = self._ready_source_with_chunks(["Warranty covers manufacturing defects only."], name="filed")
        library = create_library(self.team.id, "Docs")
        self._file_source(library.id, filed.id)

        results = search_knowledge_for_team(
            child, "refund warranty", trace=RetrievalTrace(surface="api"), library_id=library.id
        )

        assert {result.source_name for result in results} == {"filed"}

    @patch("products.business_knowledge.backend.logic._semantic_chunk_candidates")
    def test_library_scoped_semantic_search_drops_other_sources(self, mock_semantic: MagicMock) -> None:
        filed = self._ready_source_with_chunks(["The refund policy states thirty day returns."], name="refund")
        outsider = self._ready_source_with_chunks(["Warranty covers manufacturing defects only."], name="warranty")
        library = create_library(self.team.id, "Docs")
        self._file_source(library.id, filed.id)
        mock_semantic.return_value = [_SemanticCandidate(chunk_id=self._get_chunk_ids(outsider)[0], distance=0.1)]

        results = search_knowledge(
            self.team.id,
            "refund policy",
            use_semantic=True,
            query_embedding=[0.1] * 10,
            library_id=library.id,
        )

        assert {result.source_name for result in results} == {"refund"}

    @patch("products.business_knowledge.backend.logic.BK_LIBRARY_SEMANTIC_DOCUMENT_CAP", 0)
    @patch("products.business_knowledge.backend.logic._semantic_chunk_candidates")
    def test_an_oversized_library_keeps_a_member_ranked_behind_other_sources(self, mock_semantic: MagicMock) -> None:
        member = self._ready_source_with_chunks(["The refund policy states thirty day returns."], name="refund")
        library = create_library(self.team.id, "Docs")
        self._file_source(library.id, member.id)
        others = [_SemanticCandidate(chunk_id=uuid.uuid4(), distance=0.1) for _ in range(8)]
        member_candidate = _SemanticCandidate(chunk_id=self._get_chunk_ids(member)[0], distance=0.2)
        mock_semantic.return_value = [*others, member_candidate]

        results = search_knowledge(
            self.team.id,
            "how long can customers send items back",
            use_semantic=True,
            query_embedding=[0.1] * 10,
            library_id=library.id,
        )

        assert {result.source_name for result in results} == {"refund"}

    @patch("products.business_knowledge.backend.logic._semantic_chunk_candidates")
    def test_an_empty_library_returns_nothing_and_skips_clickhouse(self, mock_semantic: MagicMock) -> None:
        self._ready_source_with_chunks(["The refund policy states thirty day returns."])
        library = create_library(self.team.id, "Empty")

        results = search_knowledge(
            self.team.id,
            "refund policy",
            use_semantic=True,
            query_embedding=[0.1] * 10,
            library_id=library.id,
        )

        assert results == []
        mock_semantic.assert_not_called()

    @parameterized.expand(
        [
            (
                "unsafe_verdict",
                lambda t, s: KnowledgeDocument.objects.filter(source_id=s.id).update(
                    safety_verdict=SafetyVerdict.UNSAFE
                ),
            ),
            (
                "tombstoned",
                lambda t, s: KnowledgeDocument.objects.filter(source_id=s.id).update(tombstoned_at=timezone.now()),
            ),
            (
                "source_not_ready",
                lambda t, s: KnowledgeSource.objects.filter(id=s.id).update(status=SourceStatus.PROCESSING),
            ),
        ]
    )
    @patch("products.business_knowledge.backend.logic._semantic_chunk_candidates")
    def test_rejoin_filters_ineligible_chunks(self, _name: str, mark_ineligible, mock_semantic: MagicMock) -> None:  # noqa: ANN001
        source = self._ready_source_with_chunks(["Some indexed content here."])
        chunk_ids = self._get_chunk_ids(source)

        with team_scope(self.team.id, canonical=True):
            mark_ineligible(self.team, source)

        mock_semantic.return_value = [_SemanticCandidate(chunk_id=chunk_ids[0], distance=0.2)]

        results = search_knowledge(
            self.team.id,
            "indexed content",
            use_semantic=True,
            query_embedding=[0.1] * 10,
        )
        assert results == []

    @patch("products.business_knowledge.backend.logic._semantic_chunk_candidates")
    def test_overfetch_still_yields_results_after_filtering(self, mock_semantic: MagicMock) -> None:
        # Create two sources: one SAFE, one will be tombstoned
        src_safe = self._ready_source_with_chunks(["Safe searchable chunk about dogs."], name="safe_src")
        src_dead = self._ready_source_with_chunks(["Dead chunk about dogs too."], name="dead_src")

        safe_ids = self._get_chunk_ids(src_safe)
        dead_ids = self._get_chunk_ids(src_dead)

        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=src_dead.id).update(tombstoned_at=timezone.now())

        # Semantic returns the dead chunk first (closer vector), then the safe one
        mock_semantic.return_value = [
            _SemanticCandidate(chunk_id=dead_ids[0], distance=0.1),
            _SemanticCandidate(chunk_id=safe_ids[0], distance=0.3),
        ]

        results = search_knowledge(
            self.team.id,
            "dogs",
            use_semantic=True,
            query_embedding=[0.1] * 10,
            limit=2,
        )
        # Dead chunk filtered, safe chunk survives
        assert len(results) >= 1
        result_ids = {r.chunk_id for r in results}
        assert safe_ids[0] in result_ids
        assert dead_ids[0] not in result_ids

    def test_no_embedding_falls_back_to_fts(self) -> None:
        self._ready_source_with_chunks(["The refund policy states thirty day returns."])
        # use_semantic=True but no embedding → falls back to FTS only
        results = search_knowledge(
            self.team.id,
            "refund policy",
            use_semantic=True,
            query_embedding=None,
        )
        # Should still find results via FTS
        assert len(results) >= 1


class TestDocumentWindow(BaseTest):
    """Tests for get_document_window drill-down logic."""

    def _create_source_with_chunks(
        self, num_chunks: int, *, safe: bool = True, name: str = "src"
    ) -> tuple[KnowledgeSource, KnowledgeDocument]:
        """Create a source with exactly num_chunks chunks (bypasses chunker)."""
        with team_scope(self.team.id, canonical=True):
            source = KnowledgeSource.objects.create(
                team_id=self.team.id,
                name=name,
                source_type="text",
                status=SourceStatus.READY,
            )
            doc = KnowledgeDocument.objects.create(
                team_id=self.team.id,
                source=source,
                title=f"Doc for {name}",
                safety_verdict=SafetyVerdict.SAFE if safe else SafetyVerdict.UNKNOWN,
            )
            chunks = []
            for i in range(num_chunks):
                content = f"Content of chunk {i} in document."
                chunks.append(
                    KnowledgeChunk(
                        id=uuid.uuid4(),
                        team_id=self.team.id,
                        source=source,
                        document=doc,
                        ordinal=i,
                        content=content,
                        heading_path=f"Section {i}",
                        char_count=len(content),
                    )
                )
            KnowledgeChunk.objects.bulk_create(chunks)
        return source, doc

    @parameterized.expand(
        [
            ("contiguous_span", 10, 5, 2, [3, 4, 5, 6, 7]),
            ("radius_zero", 5, 2, 0, [2]),
            ("edge_no_wrap", 5, 0, 3, [0, 1, 2, 3]),
            ("negative_center_clamped_to_zero", 5, -3, 2, [0, 1, 2]),
        ]
    )
    def test_ordinal_window(self, _name: str, num_chunks: int, center: int, radius: int, expected: list[int]) -> None:
        _source, doc = self._create_source_with_chunks(num_chunks)

        results = get_document_window(self.team.id, doc.id, center_ordinal=center, radius=radius)

        assert [r.ordinal for r in results] == expected

    def test_radius_clamped_to_max(self) -> None:
        _source, doc = self._create_source_with_chunks(40)

        results = get_document_window(self.team.id, doc.id, center_ordinal=20, radius=100)

        ordinals = [r.ordinal for r in results]
        low = 20 - BK_DRILLDOWN_MAX_RADIUS
        high = 20 + BK_DRILLDOWN_MAX_RADIUS
        assert all(low <= o <= high for o in ordinals)
        assert len(ordinals) <= 2 * BK_DRILLDOWN_MAX_RADIUS + 1

    @parameterized.expand(
        [
            (
                "unsafe_verdict",
                lambda doc: KnowledgeDocument.objects.filter(id=doc.id).update(safety_verdict=SafetyVerdict.UNSAFE),
            ),
            (
                "tombstoned",
                lambda doc: KnowledgeDocument.objects.filter(id=doc.id).update(tombstoned_at=timezone.now()),
            ),
            (
                "source_not_ready",
                lambda doc: KnowledgeSource.objects.filter(id=doc.source_id).update(status=SourceStatus.PROCESSING),
            ),
        ]
    )
    def test_safety_filters_return_empty(self, _name: str, mark_ineligible) -> None:  # noqa: ANN001
        _source, doc = self._create_source_with_chunks(3)

        with team_scope(self.team.id, canonical=True):
            mark_ineligible(doc)

        results = get_document_window(self.team.id, doc.id, center_ordinal=0, radius=5)
        assert results == []

    def test_cross_team_returns_empty(self) -> None:
        from posthog.models.team import Team

        _source, doc = self._create_source_with_chunks(3)

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        results = get_document_window(other_team.id, doc.id, center_ordinal=0, radius=5)
        assert results == []

    def test_unknown_document_returns_empty(self) -> None:
        results = get_document_window(self.team.id, uuid.uuid4(), center_ordinal=0, radius=5)
        assert results == []

    def test_result_fields_populated(self) -> None:
        _source, doc = self._create_source_with_chunks(3, name="my_source")

        results = get_document_window(self.team.id, doc.id, center_ordinal=0, radius=0)

        assert len(results) == 1
        r = results[0]
        assert r.document_id == doc.id
        assert r.source_name == "my_source"
        assert "Content of chunk 0" in r.content


class TestLibrarySemanticDocumentPredicate(ClickhouseTestMixin, BaseTest):
    """The embedding row's document_id column is the chunk id. The knowledge document id is only in metadata."""

    def test_library_filter_uses_metadata_document_id(self) -> None:
        from datetime import UTC, datetime

        from posthog.clickhouse.client import sync_execute

        from products.business_knowledge.backend.constants import (
            BK_EMBEDDING_DOCUMENT_TYPE,
            BK_EMBEDDING_PRODUCT,
            BK_EMBEDDING_RENDERING,
        )

        chunk_id = uuid.uuid4()
        document_id = uuid.uuid4()
        decoy_document_id = uuid.uuid4()
        embedding = [0.0] * 1536
        embedding[0] = 1.0
        now = datetime.now(tz=UTC)
        sync_execute(
            """
            INSERT INTO distributed_posthog_document_embeddings_text_embedding_3_small_1536 (
                team_id, product, document_type, rendering, document_id, timestamp, inserted_at,
                content, metadata, embedding, _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                (
                    self.team.id,
                    BK_EMBEDDING_PRODUCT,
                    BK_EMBEDDING_DOCUMENT_TYPE,
                    BK_EMBEDDING_RENDERING,
                    str(chunk_id),
                    now,
                    now,
                    "",
                    f'{{"document_id": "{document_id}"}}',
                    embedding,
                    now,
                    0,
                    0,
                ),
                (
                    self.team.id,
                    BK_EMBEDDING_PRODUCT,
                    BK_EMBEDDING_DOCUMENT_TYPE,
                    BK_EMBEDDING_RENDERING,
                    str(document_id),
                    now,
                    now,
                    "",
                    f'{{"document_id": "{decoy_document_id}"}}',
                    embedding,
                    now,
                    1,
                    0,
                ),
            ],
            flush=True,
            team_id=self.team.pk,
        )

        candidates = _semantic_chunk_candidates(
            self.team.id,
            embedding,
            limit=10,
            document_ids=[str(document_id)],
        )

        assert [candidate.chunk_id for candidate in candidates] == [chunk_id]
