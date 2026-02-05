from parameterized import parameterized

from posthog.tasks.alerts.utils import compute_insight_query_hash
from posthog.test.base import BaseTest


class TestComputeInsightQueryHash(BaseTest):
    def test_returns_none_for_none_query(self) -> None:
        assert compute_insight_query_hash(None) is None

    def test_returns_consistent_hash_for_same_query(self) -> None:
        query = {"kind": "TrendsQuery", "series": [{"event": "$pageview"}]}
        hash1 = compute_insight_query_hash(query)
        hash2 = compute_insight_query_hash(query)
        assert hash1 == hash2

    def test_returns_same_hash_regardless_of_key_order(self) -> None:
        query1 = {"kind": "TrendsQuery", "series": [{"event": "$pageview"}]}
        query2 = {"series": [{"event": "$pageview"}], "kind": "TrendsQuery"}
        assert compute_insight_query_hash(query1) == compute_insight_query_hash(query2)

    def test_returns_different_hash_for_different_queries(self) -> None:
        query1 = {"kind": "TrendsQuery", "series": [{"event": "$pageview"}]}
        query2 = {"kind": "TrendsQuery", "series": [{"event": "$pageleave"}]}
        assert compute_insight_query_hash(query1) != compute_insight_query_hash(query2)

    def test_returns_64_char_hex_string(self) -> None:
        query = {"kind": "TrendsQuery"}
        hash_result = compute_insight_query_hash(query)
        assert hash_result is not None
        assert len(hash_result) == 64
        assert all(c in "0123456789abcdef" for c in hash_result)

    @parameterized.expand(
        [
            ({"a": 1, "b": 2}, {"b": 2, "a": 1}),
            ({"nested": {"x": 1, "y": 2}}, {"nested": {"y": 2, "x": 1}}),
            ({"list": [1, 2, 3]}, {"list": [1, 2, 3]}),
        ]
    )
    def test_key_order_independence(self, query1: dict, query2: dict) -> None:
        assert compute_insight_query_hash(query1) == compute_insight_query_hash(query2)
