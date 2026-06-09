import uuid
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.constants import BK_DRILLDOWN_MAX_RADIUS, BK_RRF_SCORE_FLOOR
from products.business_knowledge.backend.logic import (
    _rrf_fuse,
    _SemanticCandidate,
    get_document_window,
    search_knowledge,
)
from products.business_knowledge.backend.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SafetyVerdict,
    SourceStatus,
)


class TestRRFFusion(BaseTest):
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
    """Tests for the agentic drill-down read primitive (`get_document_window`)."""

    def _multi_chunk_source(self, n: int = 6, name: str = "doc") -> tuple[KnowledgeSource, UUID, list[int]]:
        # Each paragraph is padded past CHUNK_TARGET_CHARS so the chunker keeps
        # them as separate ordinals (0..n-1) within a single document.
        paragraphs = [f"MARKER{i} " + ("filler word " * 120) for i in range(n)]
        source = logic.create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name=name,
            text="\n\n".join(paragraphs),
        )
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
            document_id = KnowledgeDocument.objects.filter(source_id=source.id).values_list("id", flat=True)[0]
            ordinals = list(
                KnowledgeChunk.objects.filter(source_id=source.id).order_by("ordinal").values_list("ordinal", flat=True)
            )
        return source, document_id, ordinals

    def test_returns_contiguous_span_around_center(self) -> None:
        _source, document_id, ordinals = self._multi_chunk_source(n=6)
        assert len(ordinals) >= 5  # chunker produced multiple chunks

        results = get_document_window(self.team.id, document_id, center_ordinal=2, radius=1)
        returned = sorted(r.ordinal for r in results)
        assert returned == [1, 2, 3]
        # span is wider than search's fixed +/-1 when radius is larger
        wider = get_document_window(self.team.id, document_id, center_ordinal=2, radius=2)
        assert sorted(r.ordinal for r in wider) == [0, 1, 2, 3, 4]

    def test_radius_clamped_to_max(self) -> None:
        _source, document_id, ordinals = self._multi_chunk_source(n=6)
        # An absurd radius can't pull more than the document has, and never errors.
        results = get_document_window(self.team.id, document_id, center_ordinal=0, radius=10_000)
        assert len(results) == len(ordinals)
        assert max(r.ordinal for r in results) == max(ordinals)

    def test_edges_do_not_wrap_or_error(self) -> None:
        _source, document_id, _ordinals = self._multi_chunk_source(n=4)
        results = get_document_window(self.team.id, document_id, center_ordinal=0, radius=2)
        assert sorted(r.ordinal for r in results) == [0, 1, 2]

    @parameterized.expand(
        [
            (
                "unsafe_verdict",
                lambda s: KnowledgeDocument.objects.filter(source_id=s.id).update(safety_verdict=SafetyVerdict.UNSAFE),
            ),
            (
                "tombstoned",
                lambda s: KnowledgeDocument.objects.filter(source_id=s.id).update(tombstoned_at=timezone.now()),
            ),
            (
                "source_not_ready",
                lambda s: KnowledgeSource.objects.filter(id=s.id).update(status=SourceStatus.PROCESSING),
            ),
        ]
    )
    def test_ineligible_document_returns_empty(self, _name: str, mark_ineligible) -> None:  # noqa: ANN001
        source, document_id, _ordinals = self._multi_chunk_source(n=4)
        with team_scope(self.team.id, canonical=True):
            mark_ineligible(source)

        results = get_document_window(self.team.id, document_id, center_ordinal=1, radius=2)
        assert results == []

    def test_cross_team_document_returns_empty(self) -> None:
        # The document belongs to self.team; reading it under another team's id
        # must yield nothing (team_id re-join holds — no IDOR).
        _source, document_id, _ordinals = self._multi_chunk_source(n=4)
        other_team = Team.objects.create(organization=self.organization, name="other")

        results = get_document_window(other_team.id, document_id, center_ordinal=1, radius=BK_DRILLDOWN_MAX_RADIUS)
        assert results == []

    def test_unknown_document_returns_empty(self) -> None:
        results = get_document_window(self.team.id, uuid.uuid4(), center_ordinal=0, radius=3)
        assert results == []
