from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import DashboardFilter

from posthog.hogql_queries.apply_dashboard_filters import (
    dashboard_filter_from_dict,
    flatten_property_leaves,
    merge_filters_by_priority,
    remove_query_properties_overridden_by,
    resolve_effective_dashboard_filters,
    resolve_filter_layers_by_priority,
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

    def test_tile_property_replaces_dashboard_property_when_they_contradict(self):
        # Disjoint exact sets on the same key can never both match, so the tile wins outright rather than
        # AND-ing (which would zero out results).
        dashboard_prop = {"key": "$browser", "value": ["Chrome", "Safari"], "type": "event", "operator": "exact"}
        tile_prop = {"key": "$browser", "value": ["Firefox"], "type": "event", "operator": "exact"}

        merged = merge_filters_by_priority(
            {"properties": [dashboard_prop]},
            {"properties": [tile_prop]},
        )
        resolved_layers = resolve_filter_layers_by_priority(
            {"properties": [dashboard_prop]},
            {"properties": [tile_prop]},
        )

        assert merged["properties"] == [tile_prop]
        assert resolved_layers == {
            "dashboard": {},
            "tile": {"properties": [tile_prop]},
            "overridden_dashboard": {"properties": [dashboard_prop]},
        }

    def test_compatible_properties_on_same_key_stack_instead_of_replacing(self):
        # `utm_source = google` and `utm_source is set` describe a valid combined set, so both apply
        # rather than the tile dropping the dashboard's filter.
        dashboard_prop = {"key": "utm_source", "value": ["google"], "type": "event", "operator": "exact"}
        tile_prop = {"key": "utm_source", "type": "event", "operator": "is_set"}

        merged = merge_filters_by_priority(
            {"properties": [dashboard_prop]},
            {"properties": [tile_prop]},
        )

        assert merged["properties"] == [dashboard_prop, tile_prop]

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

    def test_same_key_on_different_group_types_are_not_treated_as_the_same_filter(self):
        dashboard_prop = {"key": "name", "value": "Acme", "type": "group", "group_type_index": 0}
        tile_prop = {"key": "name", "value": "Beta", "type": "group", "group_type_index": 1}

        merged = merge_filters_by_priority(
            {"properties": [dashboard_prop]},
            {"properties": [tile_prop]},
        )

        assert merged["properties"] == [dashboard_prop, tile_prop]

    def test_tile_property_with_non_string_key_does_not_raise(self):
        # `key` comes from unvalidated client JSON and can be a list; contradiction detection must not crash.
        merged = merge_filters_by_priority(
            {"properties": [{"key": "browser", "type": "event", "value": "x"}]},
            {"properties": [{"key": ["a", "b"], "type": "event", "value": "y"}]},
        )
        assert len(merged["properties"]) == 2

    def test_and_property_group_dicts_are_flattened_for_conflict_resolution(self):
        country_prop = {"key": "$country", "value": "US", "type": "event"}
        dashboard_browser_prop = {
            "key": "$browser",
            "value": ["Chrome"],
            "type": "event",
            "operator": "exact",
        }
        tile_browser_prop = {
            "key": "$browser",
            "value": ["Firefox"],
            "type": "event",
            "operator": "exact",
        }

        merged = merge_filters_by_priority(
            {"properties": {"type": "AND", "values": [country_prop, dashboard_browser_prop]}},
            {"properties": {"type": "AND", "values": [tile_browser_prop]}},
        )

        assert merged["properties"] == [country_prop, tile_browser_prop]


class TestDashboardFilterFromDict(SimpleTestCase):
    def test_property_group_dict_is_flattened_instead_of_raising(self):
        # `DashboardFilter.properties` is typed as a flat list, so a property-group dict used to raise a
        # pydantic ValidationError (500) at the construction sites in calculate_results and
        # apply_dashboard_filters_to_dict. It must be flattened to leaves instead.
        built = dashboard_filter_from_dict(
            {
                "date_from": "-7d",
                "properties": {
                    "type": "AND",
                    "values": [{"type": "AND", "values": [{"key": "$browser", "value": "Chrome", "type": "event"}]}],
                },
            }
        )
        assert built.properties is not None
        assert [p.model_dump(exclude_none=True, mode="json") for p in built.properties] == [
            {"key": "$browser", "type": "event", "value": "Chrome", "operator": "exact"}
        ]
        assert built.date_from == "-7d"


class TestFlattenPropertyLeaves(SimpleTestCase):
    def test_rejects_or_property_group(self):
        or_group = {
            "type": "OR",
            "values": [
                {"key": "$country", "value": "US", "type": "event"},
                {"key": "$country", "value": "CA", "type": "event"},
            ],
        }
        with self.assertRaisesRegex(ValueError, "Only AND property groups are supported"):
            flatten_property_leaves(or_group)


class TestResolveEffectiveDashboardFilters(SimpleTestCase):
    def test_normalizes_single_layer_dict_properties_to_flat_list(self):
        prop = {"key": "$browser", "value": "Chrome", "type": "event"}
        query = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}}
        _, effective = resolve_effective_dashboard_filters(
            query, {"date_from": "-7d", "properties": {"type": "AND", "values": [prop]}}, None
        )
        assert effective["properties"] == [prop]
        assert effective["date_from"] == "-7d"


class TestIgnoreDashboardFilters(SimpleTestCase):
    _DASHBOARD = {
        "date_from": "-30d",
        "properties": [{"key": "$browser", "value": "Chrome", "type": "event"}],
        "interval": "day",
        "filterTestAccounts": True,
    }

    @parameterized.expand(
        [
            ("dashboard has filters", _DASHBOARD),
            ("dashboard empty", None),
        ]
    )
    def test_flag_drops_dashboard_layer_and_keeps_tile_values(self, _name, dashboard):
        merged = merge_filters_by_priority(dashboard, {"ignoreDashboardFilters": True, "date_from": "-7d"})

        assert merged == {"date_from": "-7d"}
        DashboardFilter(**merged)  # the flag must never reach the extra="forbid" model

    def test_flag_only_tile_yields_empty_effective_filters(self):
        merged = merge_filters_by_priority(self._DASHBOARD, {"ignoreDashboardFilters": True})

        assert merged == {}

    def test_flag_with_property_group_tile_filters_flattens_for_query_application(self):
        merged = merge_filters_by_priority(
            self._DASHBOARD,
            {
                "ignoreDashboardFilters": True,
                "properties": {
                    "type": "AND",
                    "values": [{"type": "AND", "values": [{"key": "$browser", "value": "Chrome", "type": "event"}]}],
                },
            },
        )

        assert merged == {"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]}

    def test_false_flag_merges_normally_and_is_stripped(self):
        merged = merge_filters_by_priority({"date_from": "-30d"}, {"ignoreDashboardFilters": False, "interval": "week"})

        assert merged == {"date_from": "-30d", "interval": "week"}
        DashboardFilter(**merged)

    @parameterized.expand(
        [
            ("no tile override", None, {"date_from": "-30d"}),
            (
                "tile override present",
                {"interval": "week"},
                {"date_from": "-30d", "interval": "week"},
            ),
        ]
    )
    def test_flag_in_base_layer_is_stripped_without_dropping_the_layer(self, _name, tile, expected):
        base = {"ignoreDashboardFilters": True, "date_from": "-30d"}

        merged = merge_filters_by_priority(base, tile)

        assert merged == expected
        DashboardFilter(**merged)

    def test_flag_in_base_layer_does_not_reach_effective_filters(self):
        query = {"kind": "TrendsQuery", "series": []}

        _, effective = resolve_effective_dashboard_filters(
            query, {"ignoreDashboardFilters": True, "date_from": "-30d"}, None
        )

        assert effective == {"date_from": "-30d"}
        DashboardFilter(**effective)

    def test_dashboard_filter_from_dict_strips_flag(self):
        assert dashboard_filter_from_dict({"ignoreDashboardFilters": True, "date_from": "-30d"}) == DashboardFilter(
            date_from="-30d"
        )

    def test_resolve_layers_reports_dashboard_as_fully_overridden(self):
        tile_prop = {"key": "$country", "value": "US", "type": "event"}

        resolved = resolve_filter_layers_by_priority(
            self._DASHBOARD, {"ignoreDashboardFilters": True, "properties": [tile_prop]}
        )

        assert resolved == {
            "dashboard": {},
            "tile": {"ignoreDashboardFilters": True, "properties": [tile_prop]},
            "overridden_dashboard": self._DASHBOARD,
        }


class TestRemoveQueryPropertiesOverriddenBy(SimpleTestCase):
    def _query(self, properties):
        return {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "properties": properties}}

    def test_strips_insight_property_the_tile_contradicts(self):
        query = self._query(
            [
                {"key": "$browser", "value": "Chrome", "type": "event"},
                {"key": "$country", "value": "US", "type": "event"},
            ]
        )
        tile = {"properties": [{"key": "$browser", "value": "Firefox", "type": "event"}]}

        stripped = remove_query_properties_overridden_by(query, tile)

        assert stripped["source"]["properties"] == [{"key": "$country", "value": "US", "type": "event"}]

    @parameterized.expand([("TrendsQuery",), ("FunnelsQuery",), ("LifecycleQuery",)])
    def test_strips_contradicted_series_property(self, query_kind):
        query = {
            "kind": "InsightVizNode",
            "source": {
                "kind": query_kind,
                "series": [
                    {
                        "kind": "EventsNode",
                        "event": "$pageview",
                        "properties": [
                            {"key": "$browser", "value": "Chrome", "type": "event"},
                            {"key": "$country", "value": "US", "type": "event"},
                        ],
                    }
                ],
            },
        }
        overriding = {"properties": [{"key": "$browser", "value": "Firefox", "type": "event"}]}

        stripped = remove_query_properties_overridden_by(query, overriding)

        assert stripped["source"]["series"][0]["properties"] == [{"key": "$country", "value": "US", "type": "event"}]

    def test_keeps_insight_property_compatible_with_the_override(self):
        # Insight `utm_source = google` and dashboard `utm_source is set` combine into a valid set, so the
        # insight's own filter is kept to stack rather than dropped.
        query = self._query([{"key": "utm_source", "value": "google", "type": "event", "operator": "exact"}])
        overriding = {"properties": [{"key": "utm_source", "type": "event", "operator": "is_set"}]}

        assert remove_query_properties_overridden_by(query, overriding) == query

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

    def test_overriding_properties_as_property_group_dict_does_not_raise(self):
        # The overriding filters' `properties` can itself be a PropertyGroupFilter dict; it must be
        # flattened to leaves before contradiction detection rather than iterated as a dict.
        query = self._query(
            [
                {"key": "$browser", "value": "Chrome", "type": "event"},
                {"key": "$country", "value": "US", "type": "event"},
            ]
        )
        overriding = {
            "properties": {"type": "AND", "values": [{"key": "$browser", "value": "Firefox", "type": "event"}]}
        }

        stripped = remove_query_properties_overridden_by(query, overriding)

        assert stripped["source"]["properties"] == [{"key": "$country", "value": "US", "type": "event"}]

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
