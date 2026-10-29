from types import SimpleNamespace

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.resource_transfer.registry import ResourceTransferRegistryError, build_registry, get_registry
from posthog.models.resource_transfer.visitors import ActionVisitor, CohortVisitor, InsightVisitor
from posthog.models.resource_transfer.visitors.feature_flag import FeatureFlagVisitor
from posthog.models.resource_transfer.visitors.feature_flag_filters import (
    collect_action_ids_from_flag_filters,
    collect_cohort_ids_from_flag_filters,
    get_holdout_id_from_flag_filters,
)
from posthog.models.resource_transfer.visitors.survey import SurveyVisitor

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort


class TestExtractActionIds(SimpleTestCase):
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


class TestExtractCohortIds(SimpleTestCase):
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


class TestRewriteActionIdInFilters(SimpleTestCase):
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


class TestRewriteActionIdInQuery(SimpleTestCase):
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


class TestRewriteCohortIdInFilters(SimpleTestCase):
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


class TestRewriteCohortIdInQuery(SimpleTestCase):
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


class TestCohortExtractCohortIds(SimpleTestCase):
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


class TestCohortExtractActionIds(SimpleTestCase):
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


class TestCohortRewriteCohortIdInFilters(SimpleTestCase):
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


class TestCohortRewriteActionIdInFilters(SimpleTestCase):
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


class TestFeatureFlagFilterDynamicEdgeExtraction(SimpleTestCase):
    """Unit tests for cohort / action / holdout IDs embedded in feature flag ``filters`` JSON."""

    @parameterized.expand(
        [
            (
                "groups_cohort_property",
                {
                    "groups": [
                        {
                            "properties": [
                                {"key": "id", "value": 10, "type": "cohort"},
                            ]
                        }
                    ]
                },
                {10},
            ),
            (
                "super_groups_and_groups_deduped",
                {
                    "groups": [
                        {"properties": [{"key": "id", "value": 1, "type": "cohort"}]},
                    ],
                    "super_groups": [
                        {
                            "properties": [
                                {"key": "id", "value": 1, "type": "cohort"},
                                {"key": "id", "value": 2, "type": "cohort"},
                            ]
                        },
                    ],
                },
                {1, 2},
            ),
            ("empty", {}, set()),
            ("none", None, set()),
        ]
    )
    def test_collect_cohort_ids_from_flag_filters(self, _name: str, filters, expected: set[int]) -> None:
        assert collect_cohort_ids_from_flag_filters(filters) == expected

    @parameterized.expand(
        [
            (
                "behavioral_action_in_group",
                {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": 404,
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "event_type": "actions",
                                }
                            ]
                        }
                    ]
                },
                {404},
            ),
            (
                "groups_and_super_groups",
                {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": 1,
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "event_type": "actions",
                                }
                            ]
                        }
                    ],
                    "super_groups": [
                        {
                            "properties": [
                                {
                                    "key": 2,
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "event_type": "actions",
                                }
                            ]
                        }
                    ],
                },
                {1, 2},
            ),
        ]
    )
    def test_collect_action_ids_from_flag_filters(self, _name: str, filters, expected: set[int]) -> None:
        assert collect_action_ids_from_flag_filters(filters) == expected

    @parameterized.expand(
        [
            ("with_holdout", {"holdout": {"id": 99, "exclusion_percentage": 10}}, 99),
            ("no_holdout", {"groups": []}, None),
            ("holdout_missing_id", {"holdout": {}}, None),
        ]
    )
    def test_get_holdout_id_from_flag_filters(self, _name: str, filters, expected: int | None) -> None:
        assert get_holdout_id_from_flag_filters(filters) == expected


class TestFeatureFlagVisitorDynamicEdges(SimpleTestCase):
    def test_dynamic_edges_include_cohort_action_and_holdout(self) -> None:
        flag = SimpleNamespace(
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "id", "value": 7, "type": "cohort"},
                            {
                                "key": 11,
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "actions",
                            },
                        ]
                    }
                ],
                "holdout": {"id": 3, "exclusion_percentage": 5},
            }
        )
        edges = FeatureFlagVisitor.get_dynamic_edges(flag)

        by_model_pk = {(e.target_model, e.target_primary_key) for e in edges}
        assert (Cohort, 7) in by_model_pk
        assert (Action, 11) in by_model_pk
        assert ("ExperimentHoldout", 3) in {e.key for e in edges}

        names = {e.name for e in edges}
        assert "cohort:7" in names
        assert "action:11" in names
        assert "holdout:3" in names


class TestSurveyVisitorConditionsCohorts(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "properties_with_cohort",
                {"properties": [{"key": "id", "value": 7, "type": "cohort"}]},
                {7},
            ),
            (
                "no_properties",
                {"url": "/pricing"},
                set(),
            ),
            (
                "empty_conditions",
                None,
                set(),
            ),
        ]
    )
    def test_extract_cohort_ids_from_conditions(self, _name: str, conditions, expected: set[int]) -> None:
        assert SurveyVisitor._extract_cohort_ids_from_conditions(conditions) == expected

    def test_rewrite_cohort_in_payload_updates_conditions_properties(self) -> None:
        payload = {
            "conditions": {
                "properties": [{"key": "id", "value": 1, "type": "cohort"}],
                "url": "/x",
            }
        }
        result = SurveyVisitor._rewrite_cohort_in_payload(payload, 1, 2)
        assert result["conditions"]["properties"][0]["value"] == 2
        assert result["conditions"]["url"] == "/x"

    def test_adjust_duplicate_payload_strips_linked_flag_variant(self) -> None:
        payload = {"conditions": {"linkedFlagVariant": "control", "url": "/a"}}
        adjusted = SurveyVisitor.adjust_duplicate_payload(payload, None, None)
        assert "linkedFlagVariant" not in adjusted["conditions"]
        assert adjusted["conditions"]["url"] == "/a"


def _registered_declarations(without_kind: str | None = None) -> list[tuple[str, object]]:
    return [("registered", visitor) for kind, visitor in get_registry().by_kind.items() if kind != without_kind]


class TestVisitorRegistry(SimpleTestCase):
    @parameterized.expand(
        [
            ("not_a_visitor", [("products.example", object)], None, "not a ResourceTransferVisitor subclass"),
            ("duplicate_kind", [("products.example", ActionVisitor)], None, "both declare a visitor for 'Action'"),
            ("missing_kind", [], "ExperimentHoldout", "No visitor is declared for ExperimentHoldout"),
        ]
    )
    def test_build_registry_rejects_declaration(
        self, _name: str, extra: list[tuple[str, object]], without_kind: str | None, message: str
    ) -> None:
        with self.assertRaisesRegex(ResourceTransferRegistryError, message):
            build_registry([*_registered_declarations(without_kind), *extra])
