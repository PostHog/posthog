from pathlib import Path
from uuid import UUID

from posthog.test.base import BaseTest

import yaml
from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.logic import create_text_source
from products.business_knowledge.backend.models import KnowledgeDocument, SafetyVerdict, SourceStatus

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _mark_team_docs_safe(team_id: int) -> None:
    # Text now starts `unknown` (classifier-gated); these retrieval tests aren't
    # about safety, so clear the team's docs to SAFE to model a classified state.
    with team_scope(team_id, canonical=True):
        KnowledgeDocument.objects.filter(team_id=team_id).update(safety_verdict=SafetyVerdict.SAFE)


def _load_eval_cases() -> list[tuple[str, str, bool]]:
    """Return (label, query, expect_found) tuples for parameterized tests."""
    with open(FIXTURES_DIR / "retrieval_eval.yaml") as f:
        data = yaml.safe_load(f)
    cases: list[tuple[str, str, bool]] = []
    for entry in data:
        source_name = entry["source_name"]
        for q in entry["queries"]:
            label = f"{source_name}|{q['query']}"
            cases.append((label, q["query"], q["expect_found"]))
    return cases


class TestRetrievalEval(BaseTest):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        with open(FIXTURES_DIR / "retrieval_eval.yaml") as f:
            data = yaml.safe_load(f)
        for entry in data:
            create_text_source(
                team_id=cls.team.id,
                created_by_id=cls.user.id,
                name=entry["source_name"],
                text=entry["text"],
            )
        _mark_team_docs_safe(cls.team.id)

    @parameterized.expand(_load_eval_cases)
    def test_search(self, _label: str, query: str, expect_found: bool) -> None:
        results = logic.search_knowledge(self.team.id, query)
        if expect_found:
            assert len(results) > 0, f"Expected results for '{query}' but got none"
        else:
            assert len(results) == 0, (
                f"Expected no results for '{query}' but got {len(results)}: {[r.source_name for r in results]}"
            )

    def test_empty_query_returns_nothing(self) -> None:
        assert logic.search_knowledge(self.team.id, "") == []
        assert logic.search_knowledge(self.team.id, "   ") == []

    def test_limit_caps_anchors_with_neighbour_expansion(self) -> None:
        # `limit` caps the number of matched anchor chunks; each anchor expands to
        # its ordinal neighbours (n-1, n, n+1), so the returned set is at most 3x.
        results = logic.search_knowledge(self.team.id, "refund", limit=1)
        assert len(results) <= 3

    def test_neighbours_are_contiguous_per_document(self) -> None:
        # Adjacency expansion must keep ordinals contiguous within each document.
        results = logic.search_knowledge(self.team.id, "refund", limit=1)
        by_doc: dict[UUID, list[int]] = {}
        for r in results:
            by_doc.setdefault(r.document_id, []).append(r.ordinal)
        for ordinals in by_doc.values():
            assert ordinals == sorted(ordinals)
            assert ordinals == list(range(ordinals[0], ordinals[0] + len(ordinals)))

    def test_multiple_anchors_per_document_expand_to_disjoint_windows(self) -> None:
        # Two non-adjacent matching chunks in one document: each anchor expands to
        # its own {n-1, n, n+1} window, and the windows stay disjoint (the gap is
        # preserved) instead of collapsing into one contiguous range.
        para = ("alpha " * 120).strip()  # ~720 chars > CHUNK_TARGET_CHARS, so one paragraph == one chunk
        match = f"zebrafish {para}"
        text = "\n\n".join([match, para, para, para, match])  # "zebrafish" lands in ordinals 0 and 4
        source = create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Zebra Doc",
            text=text,
        )
        assert source.status == SourceStatus.READY
        _mark_team_docs_safe(self.team.id)

        results = logic.search_knowledge(self.team.id, "zebrafish", limit=2)
        assert len({r.document_id for r in results}) == 1
        # anchors at 0 and 4 → windows {0,1} and {3,4} (ordinal 5 doesn't exist);
        # ordinal 2 is excluded, proving multi-anchor windowing without collapse.
        assert sorted(r.ordinal for r in results) == [0, 1, 3, 4]

    def test_results_have_source_metadata(self) -> None:
        results = logic.search_knowledge(self.team.id, "refund")
        assert len(results) > 0
        r = results[0]
        assert r.source_name == "Refund Policy"
        assert r.chunk_id is not None
        assert r.source_id is not None

    def test_ranking_returns_most_relevant_source_first(self) -> None:
        # A term that only appears in the onboarding doc must rank that doc's
        # chunk first — FTS relevance ordering, not insertion order.
        results = logic.search_knowledge(self.team.id, "tracking snippet")
        assert len(results) > 0
        assert results[0].source_name == "Onboarding Guide"

    def test_stopword_only_query_returns_nothing(self) -> None:
        # `english` config drops stopwords, so a query of only stopwords yields an
        # empty tsquery and therefore no matches (rather than erroring).
        assert logic.search_knowledge(self.team.id, "the and of") == []
