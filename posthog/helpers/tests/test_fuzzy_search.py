import pytest

from posthog.helpers.fuzzy_search import DEFAULT_SCORE_CUTOFF, fuzzy_filter, fuzzy_rank, fuzzy_score


class TestFuzzyScore:
    @pytest.mark.parametrize(
        "query,choice",
        [
            ("product analytics", "product-analytics"),
            ("product_analytics", "product-analytics"),
            ("analytics product", "product-analytics"),
            ("Product Analytics", "product-analytics"),
        ],
    )
    def test_separator_and_case_insensitive_matches_score_high(self, query: str, choice: str):
        assert fuzzy_score(query, choice) >= DEFAULT_SCORE_CUTOFF

    def test_unrelated_strings_score_low(self):
        assert fuzzy_score("billing", "product-analytics") < DEFAULT_SCORE_CUTOFF


class TestFuzzyRank:
    def test_ranks_best_match_first(self):
        ranked = fuzzy_rank("team", ["team-product", "team-design", "product-analytics"])
        assert [name for name, _ in ranked] == ["team-product", "team-design"]

    def test_drops_matches_below_cutoff(self):
        ranked = fuzzy_rank("xyzzy", ["team-product", "team-design"])
        assert ranked == []

    def test_limit_caps_results(self):
        ranked = fuzzy_rank("team", ["team-product", "team-design"], limit=1)
        assert len(ranked) == 1

    def test_lower_cutoff_is_more_permissive(self):
        names = ["team-product", "product-analytics"]
        strict = fuzzy_rank("product analytics", names, score_cutoff=90)
        loose = fuzzy_rank("product analytics", names, score_cutoff=50)
        assert [name for name, _ in strict] == ["product-analytics"]
        assert {name for name, _ in loose} == set(names)


class TestFuzzyFilter:
    @pytest.fixture
    def items(self) -> list[dict]:
        return [
            {"id": "C1", "name": "product-analytics"},
            {"id": "C2", "name": "team-product"},
            {"id": "C3", "name": "team-design"},
        ]

    def test_ranks_items_best_first(self, items: list[dict]):
        result = fuzzy_filter("product analytics", items, key=lambda c: c["name"])
        assert result[0]["id"] == "C1"

    def test_tolerates_typos(self, items: list[dict]):
        result = fuzzy_filter("analytcs", items, key=lambda c: c["name"])
        assert [c["id"] for c in result] == ["C1"]

    def test_no_match_returns_empty(self, items: list[dict]):
        assert fuzzy_filter("nonexistent channel", items, key=lambda c: c["name"]) == []

    def test_ties_preserve_input_order(self, items: list[dict]):
        result = fuzzy_filter("team", items, key=lambda c: c["name"])
        assert [c["id"] for c in result] == ["C2", "C3"]

    def test_empty_query_matches_nothing(self, items: list[dict]):
        # Callers that want "show everything" on an empty query must short-circuit before calling.
        assert fuzzy_filter("", items, key=lambda c: c["name"]) == []

    def test_empty_input_returns_empty(self):
        assert fuzzy_filter("anything", [], key=lambda c: c["name"]) == []
        assert fuzzy_rank("anything", []) == []
