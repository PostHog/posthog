from posthog.models.filters import Filter
from posthog.queries.property_optimizer import PropertyOptimizer
from posthog.test.base import BaseTest

PROPERTIES_OF_ALL_TYPES = [
    {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
    {"key": "person_prop", "value": "efg", "type": "person"},
    {"key": "id", "value": 1, "type": "cohort"},
    {"key": "tag_name", "value": ["label"], "operator": "exact", "type": "element"},
    {"key": "group_prop", "value": ["value"], "operator": "exact", "type": "group", "group_type_index": 2},
]


class TestPersonPropertySelector(BaseTest):
    def setUp(self) -> None:
        self.base_filter = Filter(data={"events": [{"id": "$pageview", "type": "events", "order": 0}]}, team=self.team)

    def test_basic_selector(self):

        filter = self.base_filter.shallow_clone(
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

        filter = self.base_filter.shallow_clone(
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "event_prop2", "value": ["foo2", "bar2"], "type": "event"},
                                {"key": "person_prop2", "value": "efg2", "type": "person"},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
                                {"key": "person_prop", "value": "efg", "type": "person"},
                            ],
                        },
                    ],
                }
            }
        )

        self.assertFalse(PropertyOptimizer.using_only_person_properties(filter.property_groups))

    def test_multilevel_selector_with_valid_OR_persons(self):

        filter = self.base_filter.shallow_clone(
            {
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "event_prop2", "value": ["foo2", "bar2"], "type": "person"},
                                {"key": "person_prop2", "value": "efg2", "type": "person"},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {"key": "event_prop", "value": ["foo", "bar"], "type": "person"},
                                {"key": "person_prop", "value": "efg", "type": "person"},
                            ],
                        },
                    ],
                }
            }
        )

        self.assertTrue(PropertyOptimizer.using_only_person_properties(filter.property_groups))


class TestPersonPushdown(BaseTest):

    maxDiff = None

    def setUp(self) -> None:
        self.base_filter = Filter(data={"events": [{"id": "$pageview", "type": "events", "order": 0}]}, team=self.team)
        self.filter_with_groups = self.base_filter.shallow_clone(
            {"properties": {"type": "AND", "values": PROPERTIES_OF_ALL_TYPES}}
        )

    def test_basic_pushdowns(self):
        property_groups = PropertyOptimizer().parse_property_groups(self.filter_with_groups.property_groups)
        inner = property_groups.inner
        outer = property_groups.outer

        assert inner is not None
        assert outer is not None

        self.assertEqual(
            inner.to_dict(), {"type": "AND", "values": [{"key": "person_prop", "value": "efg", "type": "person"}]}
        )

        self.assertEqual(
            outer.to_dict(),
            {
                "type": "AND",
                "values": [
                    {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
                    {"key": "id", "value": 1, "type": "cohort"},
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
        filter = self.base_filter.shallow_clone(
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "event_prop2", "value": ["foo2", "bar2"], "type": "event"},
                                {"key": "person_prop2", "value": "efg2", "type": "person"},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
                                {"key": "person_prop", "value": "efg", "type": "person"},
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
                "values": [{"type": "AND", "values": [{"key": "person_prop", "value": "efg", "type": "person"}]}],
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
                            {"key": "event_prop2", "value": ["foo2", "bar2"], "type": "event"},
                            {"key": "person_prop2", "value": "efg2", "type": "person"},
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
                            # {"key": "person_prop", "value": "efg", "type": "person", }, # this was pushed down
                        ],
                    },
                ],
            },
        )

    def test_person_properties_with_or_not_mixed_with_event_properties(self):
        filter = self.base_filter.shallow_clone(
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "person_prop2", "value": ["foo2", "bar2"], "type": "person"},
                                {"key": "person_prop2", "value": "efg2", "type": "person"},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
                                {"key": "person_prop", "value": "efg", "type": "person"},
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
                            {"key": "person_prop2", "value": ["foo2", "bar2"], "type": "person"},
                            {"key": "person_prop2", "value": "efg2", "type": "person"},
                        ],
                    },
                    {"type": "AND", "values": [{"key": "person_prop", "value": "efg", "type": "person"}]},
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
                            {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
                            # {"key": "person_prop", "value": "efg", "type": "person", }, # this was pushed down
                        ],
                    }
                ],
            },
        )

    def test_person_properties_mixed_with_event_properties_with_misdirection_using_nested_groups(self):
        filter = self.base_filter.shallow_clone(
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "type": "OR",
                                            "values": [
                                                {
                                                    "type": "OR",
                                                    "values": [
                                                        {
                                                            "key": "event_prop2",
                                                            "value": ["foo2", "bar2"],
                                                            "type": "event",
                                                        }
                                                    ],
                                                }
                                            ],
                                        },
                                        {
                                            "type": "AND",
                                            "values": [{"key": "person_prop2", "value": "efg2", "type": "person"}],
                                        },
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "OR",
                                    "values": [
                                        {
                                            "type": "AND",
                                            "values": [{"key": "event_prop", "value": ["foo", "bar"], "type": "event"}],
                                        }
                                    ],
                                },
                                {
                                    "type": "OR",
                                    "values": [
                                        {
                                            "type": "AND",
                                            "values": [
                                                {
                                                    "type": "OR",
                                                    "values": [
                                                        {"key": "person_prop", "value": "efg", "type": "person"}
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                },
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
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "type": "AND",
                                        "values": [
                                            {
                                                "type": "OR",
                                                "values": [{"key": "person_prop", "value": "efg", "type": "person"}],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
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
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "type": "OR",
                                        "values": [
                                            {
                                                "type": "OR",
                                                "values": [
                                                    {"key": "event_prop2", "value": ["foo2", "bar2"], "type": "event"}
                                                ],
                                            }
                                        ],
                                    },
                                    {
                                        "type": "AND",
                                        "values": [{"key": "person_prop2", "value": "efg2", "type": "person"}],
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "type": "AND",
                                        "values": [{"key": "event_prop", "value": ["foo", "bar"], "type": "event"}],
                                    }
                                ],
                            },
                            # {"type": "OR", "values": [
                            #     {"type": "AND", "values": [
                            #         {"type": "OR", "values": [{"key": "person_prop", "value": "efg", "type": "person"}]}]
                            #     }]}
                            # this was pushed down
                        ],
                    },
                ],
            },
        )


# TODO: add macobo-groups in mixture to tests as well
