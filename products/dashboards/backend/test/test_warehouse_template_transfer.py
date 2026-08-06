from unittest import TestCase
from unittest.mock import patch

from products.dashboards.backend.warehouse_template_transfer import copy_referenced_warehouse_views


def _warehouse_tile(name: str, table_name: str) -> dict:
    return {
        "name": name,
        "type": "INSIGHT",
        "query": {
            "kind": "InsightVizNode",
            "source": {"kind": "TrendsQuery", "series": [{"kind": "DataWarehouseNode", "table_name": table_name}]},
        },
        "layouts": {},
    }


_MODULE = "products.dashboards.backend.warehouse_template_transfer.copy_warehouse_views_by_name"


class TestWarehouseTemplateTileRewrite(TestCase):
    """Tile rewriting is pure JSON, so the view copy (a DB / cross-project concern) is stubbed here."""

    @patch(_MODULE, return_value={"revenue": "revenue_copy"})
    def test_renamed_view_rewrites_table_name(self, _copy) -> None:
        tiles = [_warehouse_tile("Revenue", "revenue")]

        result = copy_referenced_warehouse_views(tiles=tiles, source_team=None, target_team=None, created_by=None)

        assert result[0]["query"]["source"]["series"][0]["table_name"] == "revenue_copy"
        # Original tiles are not mutated in place.
        assert tiles[0]["query"]["source"]["series"][0]["table_name"] == "revenue"

    @patch(_MODULE, return_value={"revenue": "revenue_copy"})
    def test_renamed_view_also_rewrites_raw_hogql_reference(self, _copy) -> None:
        # A DataWarehouseNode reference is what triggers the copy; a raw-SQL tile referencing the same
        # renamed view is repointed too so the whole template stays consistent.
        tiles = [
            _warehouse_tile("Revenue", "revenue"),
            {
                "name": "SQL",
                "type": "INSIGHT",
                "query": {"kind": "HogQLQuery", "query": "SELECT amount FROM revenue WHERE amount > 0"},
                "layouts": {},
            },
        ]

        result = copy_referenced_warehouse_views(tiles=tiles, source_team=None, target_team=None, created_by=None)

        assert result[0]["query"]["source"]["series"][0]["table_name"] == "revenue_copy"
        assert result[1]["query"]["query"] == "SELECT amount FROM revenue_copy WHERE amount > 0"

    @patch(_MODULE, return_value={})
    def test_no_rename_returns_tiles_unchanged(self, _copy) -> None:
        tiles = [_warehouse_tile("Revenue", "revenue")]

        result = copy_referenced_warehouse_views(tiles=tiles, source_team=None, target_team=None, created_by=None)

        assert result is tiles

    @patch(_MODULE)
    def test_no_warehouse_reference_skips_copy(self, mock_copy) -> None:
        tiles = [
            {
                "name": "Events only",
                "type": "INSIGHT",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode"}]},
                },
                "layouts": {},
            }
        ]

        result = copy_referenced_warehouse_views(tiles=tiles, source_team=None, target_team=None, created_by=None)

        assert result is tiles
        mock_copy.assert_not_called()
