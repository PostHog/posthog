from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql_queries.apply_dashboard_filters import merge_dashboard_and_tile_filters


class TestMergeDashboardAndTileFilters(SimpleTestCase):
    @parameterized.expand(
        [
            ("both empty", None, None, None),
            ("only dashboard", {"date_from": "-30d"}, None, {"date_from": "-30d"}),
            ("only tile", None, {"date_from": "-7d"}, {"date_from": "-7d"}),
            ("empty tile keeps dashboard", {"date_from": "-30d"}, {}, {"date_from": "-30d"}),
        ]
    )
    def test_returns_single_layer_when_other_absent(self, _name, dashboard, tile, expected):
        assert merge_dashboard_and_tile_filters(dashboard, tile) == expected

    def test_tile_scalar_fields_win_over_dashboard(self):
        merged = merge_dashboard_and_tile_filters(
            {"interval": "day", "filterTestAccounts": False},
            {"interval": "week", "filterTestAccounts": True},
        )
        assert merged == {"interval": "week", "filterTestAccounts": True}

    def test_dashboard_scalar_kept_when_tile_leaves_it_unset(self):
        merged = merge_dashboard_and_tile_filters(
            {"interval": "day", "filterTestAccounts": True},
            {"breakdown_filter": {"breakdown": "$browser", "breakdown_type": "event"}},
        )
        assert merged["interval"] == "day"
        assert merged["filterTestAccounts"] is True
        assert merged["breakdown_filter"] == {"breakdown": "$browser", "breakdown_type": "event"}

    def test_properties_are_and_combined_dashboard_first(self):
        dashboard_prop = {"key": "$country", "value": "US", "type": "event"}
        tile_prop = {"key": "$browser", "value": "Chrome", "type": "event"}

        merged = merge_dashboard_and_tile_filters(
            {"properties": [dashboard_prop]},
            {"properties": [tile_prop]},
        )

        assert merged["properties"] == [dashboard_prop, tile_prop]

    def test_date_range_treated_as_a_unit_when_tile_sets_a_bound(self):
        # Tile sets only date_from, so the dashboard's date_to must not leak through.
        merged = merge_dashboard_and_tile_filters(
            {"date_from": "-30d", "date_to": "-1d"},
            {"date_from": "-7d"},
        )
        assert merged["date_from"] == "-7d"
        assert merged["date_to"] is None

    def test_dashboard_date_range_kept_when_tile_has_no_dates(self):
        merged = merge_dashboard_and_tile_filters(
            {"date_from": "-30d", "date_to": "-1d"},
            {"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]},
        )
        assert merged["date_from"] == "-30d"
        assert merged["date_to"] == "-1d"
