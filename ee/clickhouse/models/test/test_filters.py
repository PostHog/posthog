from posthog.models.filters import Filter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.test.test_filter import TestFilter as PGTestFilters

from products.cohorts.backend.models.cohort import Cohort


class TestFilters(PGTestFilters):
    maxDiff = None

    def test_simplify_cohorts(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "operator": "icontains",
                            "value": ".com",
                            "type": "person",
                        }
                    ]
                }
            ],
        )
        cohort.calculate_people_ch(pending_version=0)

        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]})
        filter_with_groups = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "cohort", "key": "id", "value": cohort.pk}],
                }
            }
        )

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "email",
                            "operator": "icontains",
                            "value": ".com",
                        }
                    ],
                }
            },
        )

        self.assertEqual(
            filter_with_groups.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "email",
                            "operator": "icontains",
                            "value": ".com",
                        }
                    ],
                }
            },
        )

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            self.assertEqual(
                filter.simplify(self.team).properties_to_dict(),
                {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "id",
                                "value": cohort.pk,
                                "negation": False,
                                "type": "precalculated-cohort",
                            }
                        ],
                    }
                },
            )

            self.assertEqual(
                filter_with_groups.simplify(self.team).properties_to_dict(),
                {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "id",
                                "negation": False,
                                "value": cohort.pk,
                                "type": "precalculated-cohort",
                            }
                        ],
                    }
                },
            )

    def test_simplify_static_cohort(self):
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [{"type": "static-cohort", "negation": False, "key": "id", "value": cohort.pk}],
                }
            },
        )

    def test_simplify_hasdone_cohort(self):
        cohort = Cohort.objects.create(team=self.team, groups=[{"event_id": "$pageview", "days": 1}])
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [{"type": "cohort", "negation": False, "key": "id", "value": cohort.pk}],
                }
            },
        )

    def test_simplify_multi_group_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]},
                {"properties": [{"key": "$another_prop", "value": "something", "type": "person"}]},
            ],
        )
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
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
                                            "type": "person",
                                            "key": "$some_prop",
                                            "value": "something",
                                        }
                                    ],
                                },
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "type": "person",
                                            "key": "$another_prop",
                                            "value": "something",
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            },
        )

    def test_recursive_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "operator": "icontains",
                            "value": ".com",
                            "type": "person",
                        }
                    ]
                }
            ],
        )
        recursive_cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]}],
        )
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": recursive_cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "email",
                            "operator": "icontains",
                            "value": ".com",
                            "type": "person",
                        }
                    ],
                }
            },
        )

    def test_simplify_cohorts_with_recursive_negation(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "operator": "icontains",
                            "value": ".com",
                            "type": "person",
                        }
                    ]
                }
            ],
        )
        recursive_cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {"key": "email", "value": "xyz", "type": "person"},
                        {
                            "type": "cohort",
                            "key": "id",
                            "value": cohort.pk,
                            "negation": True,
                        },
                    ]
                }
            ],
        )
        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "cohort",
                        "key": "id",
                        "value": recursive_cohort.pk,
                        "negation": True,
                    }
                ]
            }
        )

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "cohort",
                            "key": "id",
                            "value": recursive_cohort.pk,
                            "negation": True,
                        }
                    ],
                }
            },
        )

    def test_simplify_cohorts_with_simple_negation(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "operator": "icontains",
                            "value": ".com",
                            "type": "person",
                        }
                    ]
                }
            ],
        )
        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "cohort",
                        "key": "id",
                        "value": cohort.pk,
                        "negation": True,
                    }
                ]
            }
        )

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "cohort",
                            "key": "id",
                            "value": cohort.pk,
                            "negation": True,
                        }
                    ],
                }
            },
        )

    def test_simplify_no_such_cohort(self):
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": 555_555}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [{"type": "cohort", "key": "id", "value": 555_555}],
                }
            },
        )

    def test_simplify_entities(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "operator": "icontains",
                            "value": ".com",
                            "type": "person",
                        }
                    ]
                }
            ],
        )
        filter = Filter(
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}],
                    }
                ]
            }
        )

        self.assertEqual(
            filter.simplify(self.team).entities_to_dict(),
            {
                "events": [
                    {
                        "type": "events",
                        "distinct_id_field": None,
                        "id": "$pageview",
                        "id_field": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_property_revenue_currency": None,
                        "math_group_type_index": None,
                        "custom_name": None,
                        "order": None,
                        "name": "$pageview",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "operator": "icontains",
                                    "value": ".com",
                                    "type": "person",
                                }
                            ],
                        },
                        "table_name": None,
                        "timestamp_field": None,
                    }
                ]
            },
        )

    def test_simplify_entities_with_group_math(self):
        filter = Filter(
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "math": "unique_group",
                        "math_group_type_index": 2,
                    }
                ]
            }
        )

        self.assertEqual(
            filter.simplify(self.team).entities_to_dict(),
            {
                "events": [
                    {
                        "type": "events",
                        "distinct_id_field": None,
                        "id": "$pageview",
                        "id_field": None,
                        "math": "unique_group",
                        "math_hogql": None,
                        "math_property": None,
                        "math_property_revenue_currency": None,
                        "math_group_type_index": 2,
                        "custom_name": None,
                        "order": None,
                        "name": "$pageview",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$group_2",
                                    "operator": "is_not",
                                    "value": "",
                                    "type": "event",
                                }
                            ],
                        },
                        "table_name": None,
                        "timestamp_field": None,
                    }
                ]
            },
        )

    def test_simplify_when_aggregating_by_group(self):
        filter = RetentionFilter(data={"aggregation_group_type_index": 0})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$group_0",
                            "operator": "is_not",
                            "value": "",
                            "type": "event",
                        }
                    ],
                }
            },
        )

    def test_simplify_funnel_entities_when_aggregating_by_group(self):
        filter = Filter(data={"events": [{"id": "$pageview"}], "aggregation_group_type_index": 2})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$group_2",
                            "operator": "is_not",
                            "value": "",
                            "type": "event",
                        }
                    ],
                }
            },
        )

    def test_simplify_nested(self):
        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "type": "person",
                                            "key": "email",
                                            "operator": "icontains",
                                            "value": ".com",
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "email",
                                    "operator": "icontains",
                                    "value": "arg2",
                                },
                                {
                                    "type": "person",
                                    "key": "email",
                                    "operator": "icontains",
                                    "value": "arg3",
                                },
                            ],
                        },
                    ],
                }
            }
        )

        # Can't remove the single prop groups if the parent group has multiple. The second list of conditions becomes property groups
        # because of simplify now will return prop groups by default to ensure type consistency
        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "email",
                                    "operator": "icontains",
                                    "value": ".com",
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "type": "person",
                                            "key": "email",
                                            "operator": "icontains",
                                            "value": "arg2",
                                        }
                                    ],
                                },
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "type": "person",
                                            "key": "email",
                                            "operator": "icontains",
                                            "value": "arg3",
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                }
            },
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "type": "person",
                                            "key": "email",
                                            "operator": "icontains",
                                            "value": ".com",
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "email",
                                    "operator": "icontains",
                                    "value": "arg2",
                                }
                            ],
                        },
                    ],
                }
            }
        )

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "email",
                                    "operator": "icontains",
                                    "value": ".com",
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "email",
                                    "operator": "icontains",
                                    "value": "arg2",
                                }
                            ],
                        },
                    ],
                }
            },
        )
