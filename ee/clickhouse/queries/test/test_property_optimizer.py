import unittest

from posthog.models.filters import Filter
from posthog.queries.property_optimizer import PropertyOptimizer

PROPERTIES_OF_ALL_TYPES = [
    {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
    {"key": "person_prop", "value": "efg", "type": "person"},
    {"key": "id", "value": 1, "type": "cohort"},
    {"key": "tag_name", "value": ["label"], "operator": "exact", "type": "element"},
    {"key": "group_prop", "value": ["value"], "operator": "exact", "type": "group", "group_type_index": 2},
]

BASE_FILTER = Filter({"events": [{"id": "$pageview", "type": "events", "order": 0}]})
FILTER_WITH_GROUPS = BASE_FILTER.with_data({"properties": {"type": "AND", "values": PROPERTIES_OF_ALL_TYPES}})
TEAM_ID = 3


class TestPersonPropertySelector(unittest.TestCase):
    def test_basic_selector(self):

        filter = BASE_FILTER.with_data(
            {
                "properties": {
                    "type": "OR",
                    "values": [
                        {"key": "person_prop", "value": "efg", "type": "person"},
                        {"key": "person_prop2", "value": "efg2", "type": "person"},
                    ],
                }
            }
        )
        self.assertTrue(PropertyOptimizer.using_only_person_properties(filter.property_groups))

    def test_multilevel_selector(self):

        filter = BASE_FILTER.with_data(
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "event_prop2", "value": ["foo2", "bar2"], "type": "event", "operator": None},
                                {"key": "person_prop2", "value": "efg2", "type": "person", "operator": None},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {"key": "event_prop", "value": ["foo", "bar"], "type": "event", "operator": None},
                                {"key": "person_prop", "value": "efg", "type": "person", "operator": None},
                            ],
                        },
                    ],
                }
            }
        )

        self.assertFalse(PropertyOptimizer.using_only_person_properties(filter.property_groups))

    def test_multilevel_selector_with_valid_OR_persons(self):

        filter = BASE_FILTER.with_data(
            {
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "event_prop2", "value": ["foo2", "bar2"], "type": "person", "operator": None},
                                {"key": "person_prop2", "value": "efg2", "type": "person", "operator": None},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {"key": "event_prop", "value": ["foo", "bar"], "type": "person", "operator": None},
                                {"key": "person_prop", "value": "efg", "type": "person", "operator": None},
                            ],
                        },
                    ],
                }
            }
        )

        self.assertTrue(PropertyOptimizer.using_only_person_properties(filter.property_groups))


class TestPersonPushdown(unittest.TestCase):

    maxDiff = None

    def test_basic_pushdowns(self):
        property_groups = PropertyOptimizer().parse_property_groups(FILTER_WITH_GROUPS.property_groups)
        inner = property_groups.inner
        outer = property_groups.outer

        assert inner is not None
        assert outer is not None

        self.assertEqual(
            inner.to_dict(),
            {"type": "AND", "values": [{"key": "person_prop", "value": "efg", "type": "person", "operator": None},]},
        )

        self.assertEqual(
            outer.to_dict(),
            {
                "type": "AND",
                "values": [
                    {"key": "event_prop", "value": ["foo", "bar"], "type": "event", "operator": None},
                    {"key": "id", "value": 1, "type": "cohort", "operator": None},
                    {"key": "tag_name", "value": ["label"], "operator": "exact", "type": "element"},
                    {
                        "key": "group_prop",
                        "value": ["value"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 2,
                    },
                ],
            },
        )

    def test_person_properties_mixed_with_event_properties(self):
        filter = BASE_FILTER.with_data(
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "event_prop2", "value": ["foo2", "bar2"], "type": "event", "operator": None},
                                {"key": "person_prop2", "value": "efg2", "type": "person", "operator": None},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {"key": "event_prop", "value": ["foo", "bar"], "type": "event", "operator": None},
                                {"key": "person_prop", "value": "efg", "type": "person", "operator": None},
                            ],
                        },
                    ],
                }
            }
        )

        property_groups = PropertyOptimizer().parse_property_groups(filter.property_groups)
        inner = property_groups.inner
        outer = property_groups.outer

        assert inner is not None
        assert outer is not None

        self.assertEqual(
            inner.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "person_prop", "value": "efg", "type": "person", "operator": None},],
                    }
                ],
            },
        )

        self.assertEqual(
            outer.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {"key": "event_prop2", "value": ["foo2", "bar2"], "type": "event", "operator": None},
                            {"key": "person_prop2", "value": "efg2", "type": "person", "operator": None},
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {"key": "event_prop", "value": ["foo", "bar"], "type": "event", "operator": None},
                            # {"key": "person_prop", "value": "efg", "type": "person", "operator": None}, # this was pushed down
                        ],
                    },
                ],
            },
        )

    def test_person_properties_with_or_not_mixed_with_event_properties(self):
        filter = BASE_FILTER.with_data(
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "person_prop2", "value": ["foo2", "bar2"], "type": "person", "operator": None},
                                {"key": "person_prop2", "value": "efg2", "type": "person", "operator": None},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {"key": "event_prop", "value": ["foo", "bar"], "type": "event", "operator": None},
                                {"key": "person_prop", "value": "efg", "type": "person", "operator": None},
                            ],
                        },
                    ],
                }
            }
        )

        property_groups = PropertyOptimizer().parse_property_groups(filter.property_groups)
        inner = property_groups.inner
        outer = property_groups.outer

        assert inner is not None
        assert outer is not None

        self.assertEqual(
            inner.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {"key": "person_prop2", "value": ["foo2", "bar2"], "type": "person", "operator": None},
                            {"key": "person_prop2", "value": "efg2", "type": "person", "operator": None},
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [{"key": "person_prop", "value": "efg", "type": "person", "operator": None},],
                    },
                ],
            },
        )

        self.assertEqual(
            outer.to_dict(),
            {
                "type": "AND",
                "values": [
                    #  OR group was pushed down, so not here anymore
                    {
                        "type": "AND",
                        "values": [
                            {"key": "event_prop", "value": ["foo", "bar"], "type": "event", "operator": None},
                            # {"key": "person_prop", "value": "efg", "type": "person", "operator": None}, # this was pushed down
                        ],
                    }
                ],
            },
        )


# TODO: add macobo-groups in mixture to tests as well
