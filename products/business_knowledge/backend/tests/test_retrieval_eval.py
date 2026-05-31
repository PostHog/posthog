from pathlib import Path

from posthog.test.base import BaseTest

import yaml
from parameterized import parameterized

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.logic import create_text_source

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
        by_doc: dict[str, list[int]] = {}
        for r in results:
            by_doc.setdefault(r.document_title, []).append(r.ordinal)
        for ordinals in by_doc.values():
            assert ordinals == sorted(ordinals)
            assert ordinals == list(range(ordinals[0], ordinals[0] + len(ordinals)))

    def test_results_have_source_metadata(self) -> None:
        results = logic.search_knowledge(self.team.id, "refund")
        assert len(results) > 0
        r = results[0]
        assert r.source_name == "Refund Policy"
        assert r.chunk_id is not None
        assert r.source_id is not None
