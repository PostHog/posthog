from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.resource_transfer.visitors import CohortVisitor, InsightVisitor


class TestExtractActionIds(BaseTest):
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


class TestExtractCohortIds(BaseTest):
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


class TestRewriteActionIdInFilters(BaseTest):
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


class TestRewriteActionIdInQuery(BaseTest):
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


class TestRewriteCohortIdInFilters(BaseTest):
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


class TestRewriteCohortIdInQuery(BaseTest):
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


class TestCohortExtractCohortIds(BaseTest):
    @parameterized.expand(
        [
            (
                "simple_cohort_reference",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "id", "type": "cohort", "value": 8814, "negation": False}],
                            }
                        ],
                    }
                },
                {8814},
            ),
            (
                "multiple_cohort_references",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "id", "type": "cohort", "value": 100},
                                    {"key": "id", "type": "cohort", "value": 200},
                                ],
                            }
                        ],
                    }
                },
                {100, 200},
            ),
            (
                "no_cohort_references",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "email", "type": "person", "value": "test@example.com"}],
                            }
                        ],
                    }
                },
                set(),
            ),
            (
                "none_filters",
                None,
                set(),
            ),
            (
                "empty_filters",
                {},
                set(),
            ),
            (
                "filters_without_properties",
                {"some_other_key": "value"},
                set(),
            ),
            (
                "multiple_groups_with_cohort",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "email", "type": "person", "value": "test@test.com"},
                                    {"key": "id", "type": "cohort", "value": 42},
                                ],
                            },
                            {
                                "type": "AND",
                                "values": [{"key": "id", "type": "cohort", "value": 43}],
                            },
                        ],
                    }
                },
                {42, 43},
            ),
        ]
    )
    def test_extract_cohort_ids(self, _name: str, filters, expected: set[int]) -> None:
        assert CohortVisitor._extract_cohort_ids(filters) == expected


class TestCohortExtractActionIds(BaseTest):
    @parameterized.expand(
        [
            (
                "behavioral_action_reference",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 42,
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "actions",
                                        "time_value": 30,
                                        "time_interval": "day",
                                    }
                                ],
                            }
                        ],
                    }
                },
                {42},
            ),
            (
                "behavioral_event_reference_ignored",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$pageview",
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "events",
                                        "time_value": 30,
                                        "time_interval": "day",
                                    }
                                ],
                            }
                        ],
                    }
                },
                set(),
            ),
            (
                "seq_event_action_reference",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$pageview",
                                        "type": "behavioral",
                                        "value": "performed_event_sequence",
                                        "event_type": "events",
                                        "seq_event": 99,
                                        "seq_event_type": "actions",
                                        "time_value": 30,
                                        "time_interval": "day",
                                    }
                                ],
                            }
                        ],
                    }
                },
                {99},
            ),
            (
                "both_key_and_seq_event_are_actions",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 10,
                                        "type": "behavioral",
                                        "value": "performed_event_sequence",
                                        "event_type": "actions",
                                        "seq_event": 20,
                                        "seq_event_type": "actions",
                                    }
                                ],
                            }
                        ],
                    }
                },
                {10, 20},
            ),
            (
                "multiple_actions_across_groups",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 1,
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "actions",
                                    }
                                ],
                            },
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 2,
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "actions",
                                    }
                                ],
                            },
                        ],
                    }
                },
                {1, 2},
            ),
            (
                "person_property_ignored",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "email", "type": "person", "value": "test@test.com"}],
                            }
                        ],
                    }
                },
                set(),
            ),
            (
                "none_filters",
                None,
                set(),
            ),
            (
                "empty_filters",
                {},
                set(),
            ),
        ]
    )
    def test_extract_action_ids(self, _name: str, filters, expected: set[int]) -> None:
        assert CohortVisitor._extract_action_ids(filters) == expected


class TestCohortRewriteCohortIdInFilters(BaseTest):
    @parameterized.expand(
        [
            (
                "replaces_matching_cohort",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "id", "type": "cohort", "value": 100}],
                            }
                        ],
                    }
                },
                100,
                999,
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "id", "type": "cohort", "value": 999}],
                            }
                        ],
                    }
                },
            ),
            (
                "ignores_non_matching_cohort",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "id", "type": "cohort", "value": 200}],
                            }
                        ],
                    }
                },
                100,
                999,
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "id", "type": "cohort", "value": 200}],
                            }
                        ],
                    }
                },
            ),
            (
                "replaces_only_matching_among_multiple",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "id", "type": "cohort", "value": 100},
                                    {"key": "id", "type": "cohort", "value": 200},
                                ],
                            }
                        ],
                    }
                },
                100,
                999,
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "id", "type": "cohort", "value": 999},
                                    {"key": "id", "type": "cohort", "value": 200},
                                ],
                            }
                        ],
                    }
                },
            ),
        ]
    )
    def test_rewrite_cohort_id_in_filters(self, _name: str, filters, old_pk, new_pk, expected) -> None:
        assert CohortVisitor._rewrite_cohort_id_in_filters(filters, old_pk, new_pk) == expected


class TestCohortRewriteActionIdInFilters(BaseTest):
    @parameterized.expand(
        [
            (
                "replaces_matching_behavioral_action_key",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 42,
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "actions",
                                    }
                                ],
                            }
                        ],
                    }
                },
                42,
                999,
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 999,
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "actions",
                                    }
                                ],
                            }
                        ],
                    }
                },
            ),
            (
                "replaces_seq_event_action",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$pageview",
                                        "type": "behavioral",
                                        "value": "performed_event_sequence",
                                        "event_type": "events",
                                        "seq_event": 42,
                                        "seq_event_type": "actions",
                                    }
                                ],
                            }
                        ],
                    }
                },
                42,
                999,
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$pageview",
                                        "type": "behavioral",
                                        "value": "performed_event_sequence",
                                        "event_type": "events",
                                        "seq_event": 999,
                                        "seq_event_type": "actions",
                                    }
                                ],
                            }
                        ],
                    }
                },
            ),
            (
                "replaces_both_key_and_seq_event",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 42,
                                        "type": "behavioral",
                                        "value": "performed_event_sequence",
                                        "event_type": "actions",
                                        "seq_event": 42,
                                        "seq_event_type": "actions",
                                    }
                                ],
                            }
                        ],
                    }
                },
                42,
                999,
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 999,
                                        "type": "behavioral",
                                        "value": "performed_event_sequence",
                                        "event_type": "actions",
                                        "seq_event": 999,
                                        "seq_event_type": "actions",
                                    }
                                ],
                            }
                        ],
                    }
                },
            ),
            (
                "ignores_event_type_events",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$pageview",
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "events",
                                    }
                                ],
                            }
                        ],
                    }
                },
                42,
                999,
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$pageview",
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "events",
                                    }
                                ],
                            }
                        ],
                    }
                },
            ),
            (
                "ignores_non_matching_action_id",
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 50,
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "actions",
                                    }
                                ],
                            }
                        ],
                    }
                },
                42,
                999,
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": 50,
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "actions",
                                    }
                                ],
                            }
                        ],
                    }
                },
            ),
        ]
    )
    def test_rewrite_action_id_in_filters(self, _name: str, filters, old_pk, new_pk, expected) -> None:
        assert CohortVisitor._rewrite_action_id_in_filters(filters, old_pk, new_pk) == expected
