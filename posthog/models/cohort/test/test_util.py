from posthog.models.cohort import Cohort
from posthog.models.cohort.util import (
    get_dependent_cohorts,
    simplified_cohort_filter_properties,
)
from posthog.test.base import BaseTest, _create_person, flush_persons_and_events


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    is_static = kwargs.pop("is_static", False)
    cohort = Cohort.objects.create(team=team, name=name, groups=groups, is_static=is_static)
    return cohort


class TestCohortUtils(BaseTest):
    def test_simplified_cohort_filter_properties_static_cohort(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"name": "test", "name": "test"},
        )
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[], is_static=True)
        flush_persons_and_events()
        cohort.insert_users_by_list(["p1"])

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": False,
                        "type": "static-cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_static_cohort_with_negation(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"name": "test", "name": "test"},
        )
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[], is_static=True)
        flush_persons_and_events()
        cohort.insert_users_by_list(["p1"])

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "static-cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_precalculated_cohort(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": False,
                        "type": "precalculated-cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_precalculated_cohort_negated(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "precalculated-cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_non_precalculated_cohort_with_behavioural_filter(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="cohortCeption",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "name", "value": "test", "type": "person"},
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 8,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                    ],
                }
            },
        )

        cohort.calculate_people_ch(pending_version=0)

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": False,
                        "type": "cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

        # with negation

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_non_precalculated_cohort_with_cohort_filter(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )
        cohort = Cohort.objects.create(
            team=self.team,
            name="cohortCeption",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "name", "value": "test", "type": "person"},
                        {
                            "key": "id",
                            "value": cohort1.pk,
                            "type": "cohort",
                            "negation": True,
                        },
                    ],
                }
            },
        )

        cohort.calculate_people_ch(pending_version=0)

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "name", "value": "test", "type": "person"}],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "id",
                                "value": cohort1.pk,
                                "type": "cohort",
                                "negation": True,
                            },
                        ],
                    },
                ],
            },
        )

        # with negation

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_non_precalculated_cohort_with_only_person_property_filters(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="cohortCeption",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"key": "name", "value": "test", "type": "person"}],
                        },
                        {
                            "type": "OR",
                            "values": [
                                {"key": "name2", "value": "test", "type": "person"},
                                {"key": "name3", "value": "test", "type": "person"},
                            ],
                        },
                    ],
                }
            },
        )

        cohort.calculate_people_ch(pending_version=0)

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "name", "value": "test", "type": "person"}],
                    },
                    {
                        "type": "OR",
                        "values": [
                            {"key": "name2", "value": "test", "type": "person"},
                            {"key": "name3", "value": "test", "type": "person"},
                        ],
                    },
                ],
            },
        )

        # with negation

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )


class TestDependentCohorts(BaseTest):
    def test_dependent_cohorts_for_simple_cohort(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        self.assertEqual(get_dependent_cohorts(cohort), [])

    def test_dependent_cohorts_for_nested_cohort(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort2 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}],
        )

        self.assertEqual(get_dependent_cohorts(cohort1), [])
        self.assertEqual(get_dependent_cohorts(cohort2), [cohort1])

    def test_dependent_cohorts_for_deeply_nested_cohort(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort2 = _create_cohort(
            team=self.team,
            name="cohort2",
            groups=[{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}],
        )

        cohort3 = _create_cohort(
            team=self.team,
            name="cohort3",
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort2.pk,
                            "type": "cohort",
                            "negation": True,
                        }
                    ]
                }
            ],
        )

        self.assertEqual(get_dependent_cohorts(cohort1), [])
        self.assertEqual(get_dependent_cohorts(cohort2), [cohort1])
        self.assertEqual(get_dependent_cohorts(cohort3), [cohort2, cohort1])

    def test_dependent_cohorts_for_circular_nested_cohort(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort2 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}],
        )

        cohort3 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort2.pk,
                            "type": "cohort",
                            "negation": True,
                        }
                    ]
                }
            ],
        )

        cohort1.groups = [{"properties": [{"key": "id", "value": cohort3.pk, "type": "cohort"}]}]
        cohort1.save()

        self.assertEqual(get_dependent_cohorts(cohort3), [cohort2, cohort1])
        self.assertEqual(get_dependent_cohorts(cohort2), [cohort1, cohort3])
        self.assertEqual(get_dependent_cohorts(cohort1), [cohort3, cohort2])

    def test_dependent_cohorts_for_complex_nested_cohort(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort2 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {
                    "properties": [
                        {"key": "name", "value": "test2", "type": "person"},
                        {"key": "id", "value": cohort1.pk, "type": "cohort"},
                    ]
                }
            ],
        )

        cohort3 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {
                    "properties": [
                        {"key": "name", "value": "test3", "type": "person"},
                        {
                            "key": "id",
                            "value": cohort2.pk,
                            "type": "cohort",
                            "negation": True,
                        },
                    ]
                }
            ],
        )

        cohort4 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort1.pk,
                            "type": "cohort",
                            "negation": True,
                        }
                    ]
                }
            ],
        )

        cohort5 = _create_cohort(
            team=self.team,
            name="cohort4",
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort2.pk,
                            "type": "cohort",
                            "negation": True,
                        },
                        {
                            "key": "id",
                            "value": cohort4.pk,
                            "type": "cohort",
                            "negation": True,
                        },
                    ]
                }
            ],
        )

        self.assertEqual(get_dependent_cohorts(cohort1), [])
        self.assertEqual(get_dependent_cohorts(cohort2), [cohort1])
        self.assertEqual(get_dependent_cohorts(cohort3), [cohort2, cohort1])
        self.assertEqual(get_dependent_cohorts(cohort4), [cohort1])
        self.assertEqual(get_dependent_cohorts(cohort5), [cohort4, cohort1, cohort2])
