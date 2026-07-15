from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql_queries.apply_dashboard_filters import (
    merge_filters_by_priority,
    remove_query_properties_overridden_by,
)


class TestMergeFiltersByPriority(SimpleTestCase):
    @parameterized.expand(
        [
            ("both empty", None, None, {}),
            ("only dashboard", {"date_from": "-30d"}, None, {"date_from": "-30d"}),
            ("only tile", None, {"date_from": "-7d"}, {"date_from": "-7d"}),
            ("empty tile keeps dashboard", {"date_from": "-30d"}, {}, {"date_from": "-30d"}),
        ]
    )
    def test_returns_single_layer_when_other_absent(self, _name, dashboard, tile, expected):
        assert merge_filters_by_priority(dashboard, tile) == expected

    def test_tile_scalar_fields_win_over_dashboard(self):
        merged = merge_filters_by_priority(
            {"interval": "day", "filterTestAccounts": False},
            {"interval": "week", "filterTestAccounts": True},
        )
        assert merged == {"interval": "week", "filterTestAccounts": True}

    def test_dashboard_scalar_kept_when_tile_leaves_it_unset(self):
        merged = merge_filters_by_priority(
            {"interval": "day", "filterTestAccounts": True},
            {"breakdown_filter": {"breakdown": "$browser", "breakdown_type": "event"}},
        )
        assert merged["interval"] == "day"
        assert merged["filterTestAccounts"] is True
        assert merged["breakdown_filter"] == {"breakdown": "$browser", "breakdown_type": "event"}

    def test_properties_on_different_keys_are_and_combined_dashboard_first(self):
        dashboard_prop = {"key": "$country", "value": "US", "type": "event"}
        tile_prop = {"key": "$browser", "value": "Chrome", "type": "event"}

        merged = merge_filters_by_priority(
            {"properties": [dashboard_prop]},
            {"properties": [tile_prop]},
        )

        assert merged["properties"] == [dashboard_prop, tile_prop]

    def test_tile_property_replaces_dashboard_property_on_same_key(self):
        # Same (type, key): the tile wins outright rather than AND-ing (which would zero out results).
        dashboard_prop = {"key": "$browser", "value": ["Chrome", "Safari"], "type": "event", "operator": "exact"}
        tile_prop = {"key": "$browser", "value": ["Firefox"], "type": "event", "operator": "exact"}

        merged = merge_filters_by_priority(
            {"properties": [dashboard_prop]},
            {"properties": [tile_prop]},
        )

        assert merged["properties"] == [tile_prop]

    def test_date_range_treated_as_a_unit_when_tile_sets_a_bound(self):
        # Tile sets only date_from, so the dashboard's date_to must not leak through.
        merged = merge_filters_by_priority(
            {"date_from": "-30d", "date_to": "-1d"},
            {"date_from": "-7d"},
        )
        assert merged["date_from"] == "-7d"
        assert merged["date_to"] is None

    @parameterized.expand(
        [
            (
                "dashboard explicitDate dropped when tile range omits it",
                {"date_from": "2026-01-01", "date_to": "2026-01-31", "explicitDate": True},
                {"date_from": "-7d"},
                None,
            ),
            (
                "tile explicitDate applied with tile range",
                {"date_from": "-30d"},
                {"date_from": "-7d", "explicitDate": True},
                True,
            ),
        ]
    )
    def test_explicit_date_follows_the_tile_range_not_the_dashboards(self, _name, dashboard, tile, expected):
        merged = merge_filters_by_priority(dashboard, tile)
        assert merged["date_from"] == "-7d"
        assert merged.get("explicitDate") is expected

    def test_dashboard_date_range_kept_when_tile_has_no_dates(self):
        merged = merge_filters_by_priority(
            {"date_from": "-30d", "date_to": "-1d"},
            {"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]},
        )
        assert merged["date_from"] == "-30d"
        assert merged["date_to"] == "-1d"

    def test_tile_property_with_unhashable_key_does_not_raise(self):
        # `key` comes from unvalidated client JSON and can be a list; must not crash the set-building.
        merged = merge_filters_by_priority(
            {"properties": [{"key": "browser", "type": "event", "value": "x"}]},
            {"properties": [{"key": ["a", "b"], "type": "event", "value": "y"}]},
        )
        assert len(merged["properties"]) == 2


class TestRemoveQueryPropertiesOverriddenBy(SimpleTestCase):
    def _query(self, properties):
        return {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "properties": properties}}

    def test_strips_insight_property_the_tile_overrides_on_same_key(self):
        query = self._query(
            [
                {"key": "$browser", "value": "Chrome", "type": "event"},
                {"key": "$country", "value": "US", "type": "event"},
            ]
        )
        tile = {"properties": [{"key": "$browser", "value": "Firefox", "type": "event"}]}

        stripped = remove_query_properties_overridden_by(query, tile)

        assert stripped["source"]["properties"] == [{"key": "$country", "value": "US", "type": "event"}]

    def test_no_op_when_tile_has_no_properties(self):
        query = self._query([{"key": "$browser", "value": "Chrome", "type": "event"}])

        assert remove_query_properties_overridden_by(query, {"date_from": "-7d"}) == query

    def test_prunes_matching_leaf_from_property_group(self):
        query = self._query(
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "$browser", "value": "Chrome", "type": "event"},
                            {"key": "$country", "value": "US", "type": "event"},
                        ],
                    }
                ],
            }
        )
        tile = {"properties": [{"key": "$browser", "value": "Firefox", "type": "event"}]}

        stripped = remove_query_properties_overridden_by(query, tile)

        assert stripped["source"]["properties"]["values"][0]["values"] == [
            {"key": "$country", "value": "US", "type": "event"}
        ]

    def test_prunes_matching_leaf_nested_three_levels_deep(self):
        # AND[OR[AND[leaf]]] — a plain PropertyGroupFilter nesting shape. A shallow, one-level-only
        # traversal would leave the innermost leaf in place despite the tile overriding it.
        query = self._query(
            {
                "type": "AND",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "$browser", "value": "Chrome", "type": "event"},
                                    {"key": "$country", "value": "US", "type": "event"},
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        tile = {"properties": [{"key": "$browser", "value": "Firefox", "type": "event"}]}

        stripped = remove_query_properties_overridden_by(query, tile)

        innermost = stripped["source"]["properties"]["values"][0]["values"][0]["values"]
        assert innermost == [{"key": "$country", "value": "US", "type": "event"}]
