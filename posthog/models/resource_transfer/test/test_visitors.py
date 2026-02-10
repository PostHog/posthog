from parameterized import parameterized

from posthog.models.resource_transfer.visitors import InsightVisitor


class TestExtractActionIds:
    @parameterized.expand(
        [
            (
                "filters_actions_list",
                {"actions": [{"id": 1, "type": "actions"}, {"id": 2, "type": "actions"}]},
                None,
                {1, 2},
            ),
            (
                "filters_exclusions_action_type",
                {"exclusions": [{"id": 3, "type": "actions"}, {"id": 4, "type": "events"}]},
                None,
                {3},
            ),
            (
                "filters_retention_entities",
                {"target_entity": {"id": 5, "type": "actions"}, "returning_entity": {"id": 6, "type": "actions"}},
                None,
                {5, 6},
            ),
            (
                "filters_retention_event_entity_ignored",
                {"target_entity": {"id": 5, "type": "events"}},
                None,
                set(),
            ),
            (
                "query_series_actions_node",
                None,
                {
                    "source": {
                        "series": [{"kind": "ActionsNode", "id": 10}, {"kind": "EventsNode", "event": "$pageview"}]
                    }
                },
                {10},
            ),
            (
                "query_funnels_exclusion",
                None,
                {"source": {"funnelsFilter": {"exclusions": [{"kind": "ActionsNode", "id": 20}]}}},
                {20},
            ),
            (
                "query_retention_entities",
                None,
                {
                    "source": {
                        "retentionFilter": {
                            "targetEntity": {"id": 30, "type": "actions"},
                            "returningEntity": {"id": 31, "type": "actions"},
                        }
                    }
                },
                {30, 31},
            ),
            (
                "query_conversion_goal",
                None,
                {"source": {"conversionGoal": {"actionId": 40}}},
                {40},
            ),
            (
                "query_source_action_id",
                None,
                {"source": {"actionId": 50}},
                {50},
            ),
            (
                "both_filters_and_query",
                {"actions": [{"id": 1, "type": "actions"}]},
                {"source": {"series": [{"kind": "ActionsNode", "id": 2}]}},
                {1, 2},
            ),
            (
                "empty_inputs",
                {},
                {},
                set(),
            ),
            (
                "none_inputs",
                None,
                None,
                set(),
            ),
        ]
    )
    def test_extract_action_ids(self, _name: str, filters, query, expected: set[int]) -> None:
        assert InsightVisitor._extract_action_ids(filters, query) == expected


class TestExtractCohortIds:
    @parameterized.expand(
        [
            (
                "filters_flat_properties",
                {"properties": [{"key": "id", "value": 100, "type": "cohort"}]},
                None,
                {100},
            ),
            (
                "filters_grouped_properties",
                {
                    "properties": {
                        "type": "AND",
                        "values": [{"type": "AND", "values": [{"key": "id", "value": 200, "type": "cohort"}]}],
                    }
                },
                None,
                {200},
            ),
            (
                "filters_entity_properties",
                {
                    "actions": [
                        {"id": 1, "type": "actions", "properties": [{"key": "id", "value": 300, "type": "cohort"}]}
                    ]
                },
                None,
                {300},
            ),
            (
                "filters_breakdown_cohort_list",
                {"breakdown_type": "cohort", "breakdown": [400, 401]},
                None,
                {400, 401},
            ),
            (
                "filters_breakdown_cohort_single",
                {"breakdown_type": "cohort", "breakdown": 500},
                None,
                {500},
            ),
            (
                "filters_breakdown_not_cohort_ignored",
                {"breakdown_type": "event", "breakdown": [1, 2]},
                None,
                set(),
            ),
            (
                "query_source_properties",
                None,
                {"source": {"properties": [{"key": "id", "value": 600, "type": "cohort"}]}},
                {600},
            ),
            (
                "query_series_properties",
                None,
                {
                    "source": {
                        "series": [
                            {"kind": "EventsNode", "properties": [{"key": "id", "value": 700, "type": "cohort"}]}
                        ]
                    }
                },
                {700},
            ),
            (
                "query_series_fixed_properties",
                None,
                {
                    "source": {
                        "series": [
                            {"kind": "EventsNode", "fixedProperties": [{"key": "id", "value": 800, "type": "cohort"}]}
                        ]
                    }
                },
                {800},
            ),
            (
                "query_breakdown_cohort",
                None,
                {"source": {"breakdownFilter": {"breakdown_type": "cohort", "breakdown": [900, 901]}}},
                {900, 901},
            ),
            (
                "filters_retention_entity_properties",
                {
                    "target_entity": {
                        "id": 1,
                        "type": "actions",
                        "properties": [{"key": "id", "value": 1000, "type": "cohort"}],
                    }
                },
                None,
                {1000},
            ),
            (
                "empty_inputs",
                {},
                {},
                set(),
            ),
        ]
    )
    def test_extract_cohort_ids(self, _name: str, filters, query, expected: set[int]) -> None:
        assert InsightVisitor._extract_cohort_ids(filters, query) == expected


class TestRewriteActionIdInFilters:
    @parameterized.expand(
        [
            (
                "replaces_matching_action_in_list",
                {"actions": [{"id": 1, "type": "actions"}, {"id": 2, "type": "actions"}]},
                1,
                99,
                {"actions": [{"id": 99, "type": "actions"}, {"id": 2, "type": "actions"}]},
            ),
            (
                "replaces_in_exclusions",
                {"exclusions": [{"id": 1, "type": "actions"}, {"id": 2, "type": "events"}]},
                1,
                99,
                {"exclusions": [{"id": 99, "type": "actions"}, {"id": 2, "type": "events"}]},
            ),
            (
                "replaces_retention_target_entity",
                {"target_entity": {"id": 1, "type": "actions"}},
                1,
                99,
                {"target_entity": {"id": 99, "type": "actions"}},
            ),
            (
                "ignores_non_matching_id",
                {"actions": [{"id": 5, "type": "actions"}]},
                1,
                99,
                {"actions": [{"id": 5, "type": "actions"}]},
            ),
        ]
    )
    def test_rewrite_action_id_in_filters(self, _name: str, filters, old_pk, new_pk, expected) -> None:
        assert InsightVisitor._rewrite_action_id_in_filters(filters, old_pk, new_pk) == expected


class TestRewriteActionIdInQuery:
    @parameterized.expand(
        [
            (
                "replaces_in_series",
                {
                    "source": {
                        "series": [{"kind": "ActionsNode", "id": 1}, {"kind": "EventsNode", "event": "$pageview"}]
                    }
                },
                1,
                99,
                {
                    "source": {
                        "series": [{"kind": "ActionsNode", "id": 99}, {"kind": "EventsNode", "event": "$pageview"}]
                    }
                },
            ),
            (
                "replaces_in_funnel_exclusions",
                {"source": {"funnelsFilter": {"exclusions": [{"kind": "ActionsNode", "id": 1}]}}},
                1,
                99,
                {"source": {"funnelsFilter": {"exclusions": [{"kind": "ActionsNode", "id": 99}]}}},
            ),
            (
                "replaces_conversion_goal",
                {"source": {"conversionGoal": {"actionId": 1}}},
                1,
                99,
                {"source": {"conversionGoal": {"actionId": 99}}},
            ),
            (
                "replaces_source_action_id",
                {"source": {"actionId": 1}},
                1,
                99,
                {"source": {"actionId": 99}},
            ),
            (
                "replaces_retention_entities",
                {"source": {"retentionFilter": {"targetEntity": {"id": 1, "type": "actions"}}}},
                1,
                99,
                {"source": {"retentionFilter": {"targetEntity": {"id": 99, "type": "actions"}}}},
            ),
            (
                "no_source_key_is_noop",
                {"kind": "InsightVizNode"},
                1,
                99,
                {"kind": "InsightVizNode"},
            ),
        ]
    )
    def test_rewrite_action_id_in_query(self, _name: str, query, old_pk, new_pk, expected) -> None:
        assert InsightVisitor._rewrite_action_id_in_query(query, old_pk, new_pk) == expected


class TestRewriteCohortIdInFilters:
    @parameterized.expand(
        [
            (
                "replaces_flat_property",
                {"properties": [{"key": "id", "value": 100, "type": "cohort"}]},
                100,
                999,
                {"properties": [{"key": "id", "value": 999, "type": "cohort"}]},
            ),
            (
                "replaces_grouped_property",
                {
                    "properties": {
                        "type": "AND",
                        "values": [{"type": "AND", "values": [{"key": "id", "value": 100, "type": "cohort"}]}],
                    }
                },
                100,
                999,
                {
                    "properties": {
                        "type": "AND",
                        "values": [{"type": "AND", "values": [{"key": "id", "value": 999, "type": "cohort"}]}],
                    }
                },
            ),
            (
                "replaces_entity_property",
                {"events": [{"id": "$pageview", "properties": [{"key": "id", "value": 100, "type": "cohort"}]}]},
                100,
                999,
                {"events": [{"id": "$pageview", "properties": [{"key": "id", "value": 999, "type": "cohort"}]}]},
            ),
            (
                "replaces_breakdown_list",
                {"breakdown_type": "cohort", "breakdown": [100, 200]},
                100,
                999,
                {"breakdown_type": "cohort", "breakdown": [999, 200]},
            ),
            (
                "replaces_breakdown_single",
                {"breakdown_type": "cohort", "breakdown": 100},
                100,
                999,
                {"breakdown_type": "cohort", "breakdown": 999},
            ),
            (
                "ignores_non_matching",
                {"properties": [{"key": "id", "value": 200, "type": "cohort"}]},
                100,
                999,
                {"properties": [{"key": "id", "value": 200, "type": "cohort"}]},
            ),
        ]
    )
    def test_rewrite_cohort_id_in_filters(self, _name: str, filters, old_pk, new_pk, expected) -> None:
        assert InsightVisitor._rewrite_cohort_id_in_filters(filters, old_pk, new_pk) == expected


class TestRewriteCohortIdInQuery:
    @parameterized.expand(
        [
            (
                "replaces_source_property",
                {"source": {"properties": [{"key": "id", "value": 100, "type": "cohort"}]}},
                100,
                999,
                {"source": {"properties": [{"key": "id", "value": 999, "type": "cohort"}]}},
            ),
            (
                "replaces_series_property",
                {
                    "source": {
                        "series": [
                            {"kind": "EventsNode", "properties": [{"key": "id", "value": 100, "type": "cohort"}]}
                        ]
                    }
                },
                100,
                999,
                {
                    "source": {
                        "series": [
                            {"kind": "EventsNode", "properties": [{"key": "id", "value": 999, "type": "cohort"}]}
                        ]
                    }
                },
            ),
            (
                "replaces_series_fixed_properties",
                {
                    "source": {
                        "series": [
                            {"kind": "EventsNode", "fixedProperties": [{"key": "id", "value": 100, "type": "cohort"}]}
                        ]
                    }
                },
                100,
                999,
                {
                    "source": {
                        "series": [
                            {"kind": "EventsNode", "fixedProperties": [{"key": "id", "value": 999, "type": "cohort"}]}
                        ]
                    }
                },
            ),
            (
                "replaces_breakdown_filter",
                {"source": {"breakdownFilter": {"breakdown_type": "cohort", "breakdown": [100, 200]}}},
                100,
                999,
                {"source": {"breakdownFilter": {"breakdown_type": "cohort", "breakdown": [999, 200]}}},
            ),
            (
                "replaces_retention_entity_property",
                {
                    "source": {
                        "retentionFilter": {
                            "targetEntity": {
                                "id": 1,
                                "type": "actions",
                                "properties": [{"key": "id", "value": 100, "type": "cohort"}],
                            }
                        }
                    }
                },
                100,
                999,
                {
                    "source": {
                        "retentionFilter": {
                            "targetEntity": {
                                "id": 1,
                                "type": "actions",
                                "properties": [{"key": "id", "value": 999, "type": "cohort"}],
                            }
                        }
                    }
                },
            ),
        ]
    )
    def test_rewrite_cohort_id_in_query(self, _name: str, query, old_pk, new_pk, expected) -> None:
        assert InsightVisitor._rewrite_cohort_id_in_query(query, old_pk, new_pk) == expected
