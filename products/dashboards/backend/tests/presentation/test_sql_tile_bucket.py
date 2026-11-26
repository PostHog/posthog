from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.dashboards.backend.presentation.views.dashboard import _sql_tile_bucket


def _sql_tile(nested: bool = False) -> dict[str, Any]:
    query = {"kind": "HogQLQuery", "query": "select 1"}
    return {"insight": {"query": {"kind": "DataVisualizationNode", "source": query} if nested else query}}


class TestSqlTileBucket(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_tiles", {"tiles": []}, "0"),
            ("trends_only", {"tiles": [{"insight": {"query": {"kind": "InsightVizNode"}}}]}, "0"),
            ("direct_and_nested_sql", {"tiles": [_sql_tile(), _sql_tile(nested=True)]}, "1-20"),
            ("twenty_one", {"tiles": [_sql_tile()] * 21}, "21-50"),
            ("fifty_one", {"tiles": [_sql_tile()] * 51}, ">50"),
            (
                "malformed_tiles_are_skipped",
                {
                    "tiles": [
                        None,
                        "tile",
                        {"insight": "broken"},
                        {"insight": {"query": ["not", "a", "dict"]}},
                        {"insight": {"query": {"kind": "DataVisualizationNode", "source": "select 1"}}},
                        _sql_tile(),
                    ]
                },
                "1-20",
            ),
            ("tiles_not_a_list", {"tiles": "oops"}, "0"),
        ]
    )
    def test_buckets_sql_tiles(self, _name: str, data: Any, expected: str) -> None:
        self.assertEqual(_sql_tile_bucket(data), expected)
