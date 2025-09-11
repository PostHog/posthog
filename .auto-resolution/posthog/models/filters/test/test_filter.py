import json
import datetime
from collections.abc import Callable
from typing import Any, Optional, cast

from freezegun import freeze_time
from posthog.test.base import (
    BaseTest,
    QueryMatchingTest,
    _create_person,
    flush_persons_and_events,
    snapshot_postgres_queries,
    snapshot_postgres_queries_context,
)

from django.db.models import CharField, F, Func, Q

from posthog.constants import FILTER_TEST_ACCOUNTS
from posthog.models import Cohort, Filter, Person, Team
from posthog.models.property import Property
from posthog.queries.base import properties_to_Q, property_group_to_Q


class TestFilter(BaseTest):
    def test_old_style_properties(self):
        filter = Filter(data={"properties": {"$browser__is_not": "IE7", "$OS": "Mac"}})
        self.assertEqual(cast(Property, filter.property_groups.values[0]).key, "$browser")
        self.assertEqual(cast(Property, filter.property_groups.values[0]).operator, "is_not")
        self.assertEqual(cast(Property, filter.property_groups.values[0]).value, "IE7")
        self.assertEqual(cast(Property, filter.property_groups.values[0]).type, "event")
        self.assertEqual(cast(Property, filter.property_groups.values[1]).key, "$OS")
        self.assertEqual(cast(Property, filter.property_groups.values[1]).operator, None)
        self.assertEqual(cast(Property, filter.property_groups.values[1]).value, "Mac")

    def test_to_dict(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "display": "ActionsLineGraph",
                "compare": True,
                "interval": "",
                "actions": [],
                "date_from": "2020-01-01T20:00:00Z",
                "search": "query",
                "client_query_id": "123",
            }
        )
        self.assertCountEqual(
            list(filter.to_dict().keys()),
            [
                "events",
                "display",
                "compare",
                "insight",
                "date_from",
                "interval",
                "smoothing_intervals",
                "breakdown_attribution_type",
                "sampling_factor",
                "search",
                "breakdown_normalize_url",
            ],
        )

    def test_simplify_test_accounts(self):
        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ]
        self.team.save()

        data = {"properties": [{"key": "attr", "value": "some_val"}]}

        filter = Filter(data=data, team=self.team)

        self.assertEqual(
            filter.properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [{"key": "attr", "value": "some_val", "type": "event"}],
                }
            },
        )
        self.assertTrue(filter.is_simplified)

        filter = Filter(data={**data, FILTER_TEST_ACCOUNTS: True}, team=self.team)

        self.assertEqual(
            filter.properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "value": "@posthog.com",
                                    "operator": "not_icontains",
                                    "type": "person",
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"key": "attr", "value": "some_val", "type": "event"}],
                        },
                    ],
                }
            },
        )
        self.assertTrue(filter.is_simplified)

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "value": "@posthog.com",
                                    "operator": "not_icontains",
                                    "type": "person",
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"key": "attr", "value": "some_val", "type": "event"}],
                        },
                    ],
                }
            },
        )


def property_to_Q_test_factory(filter_persons: Callable, person_factory):
    class TestPropertiesToQ(BaseTest):
        def test_simple_persons(self):
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["person1"],
                properties={"url": "https://whatever.com"},
            )
            person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"url": 1})
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["person3"],
                properties={"url": {"bla": "bla"}},
            )
            person_factory(team_id=self.team.pk, distinct_ids=["person4"])

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": "https://whatever.com",
                        }
                    ]
                }
            )

            results = filter_persons(filter, self.team)
            self.assertEqual(len(results), 1)

        def test_multiple_equality_persons(self):
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["person1"],
                properties={"url": "https://whatever.com"},
            )
            person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"url": 1})
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["person3"],
                properties={"url": {"bla": "bla"}},
            )
            person_factory(team_id=self.team.pk, distinct_ids=["person4"])
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["person5"],
                properties={"url": "https://example.com"},
            )

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": ["https://whatever.com", "https://example.com"],
                        }
                    ]
                }
            )

            results = filter_persons(filter, self.team)
            self.assertEqual(len(results), 2)

        def test_incomplete_data(self):
            filter = Filter(
                data={
                    "properties": [
                        {
                            "key": "$current_url",
                            "operator": "not_icontains",
                            "type": "event",
                        }
                    ]
                }
            )
            self.assertListEqual(filter.property_groups.values, [])

        def test_contains_persons(self):
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["p1"],
                properties={"url": "https://whatever.com"},
            )
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["p2"],
                properties={"url": "https://example.com"},
            )

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": "whatever",
                            "operator": "icontains",
                        }
                    ]
                }
            )

            results = filter_persons(filter, self.team)
            self.assertEqual(len(results), 1)

        def test_regex_persons(self):
            p1_uuid = str(
                person_factory(
                    team_id=self.team.pk,
                    distinct_ids=["p1"],
                    properties={"url": "https://whatever.com"},
                ).uuid
            )
            p2_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p2"]).uuid)

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": r"\.com$",
                            "operator": "regex",
                        }
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertCountEqual(results, [p1_uuid])

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": r"\.eee$",
                            "operator": "not_regex",
                        }
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertCountEqual(results, [p1_uuid, p2_uuid])

        def test_invalid_regex_persons(self):
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["p1"],
                properties={"url": "https://whatever.com"},
            )
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["p2"],
                properties={"url": "https://example.com"},
            )

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": r"?*",
                            "operator": "regex",
                        }
                    ]
                }
            )
            self.assertEqual(len(filter_persons(filter, self.team)), 0)

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": r"?*",
                            "operator": "not_regex",
                        }
                    ]
                }
            )
            self.assertEqual(len(filter_persons(filter, self.team)), 0)

        def test_is_not_persons(self):
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["p1"],
                properties={"url": "https://whatever.com"},
            )
            p2_uuid = str(
                person_factory(
                    team_id=self.team.pk,
                    distinct_ids=["p2"],
                    properties={"url": "https://example.com"},
                ).uuid
            )

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": "https://whatever.com",
                            "operator": "is_not",
                        }
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertCountEqual(results, [p2_uuid])

        def test_does_not_contain_persons(self):
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["p1"],
                properties={"url": "https://whatever.com"},
            )
            p2_uuid = str(
                person_factory(
                    team_id=self.team.pk,
                    distinct_ids=["p2"],
                    properties={"url": "https://example.com"},
                ).uuid
            )
            p3_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p3"]).uuid)
            p4_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"url": None}).uuid)

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": "whatever.com",
                            "operator": "not_icontains",
                        }
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertCountEqual(results, [p2_uuid, p3_uuid, p4_uuid])

        def test_multiple_persons(self):
            p1_uuid = str(
                person_factory(
                    team_id=self.team.pk,
                    distinct_ids=["p1"],
                    properties={"url": "https://whatever.com", "another_key": "value"},
                ).uuid
            )
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["p2"],
                properties={"url": "https://whatever.com"},
            )

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": "whatever.com",
                            "operator": "icontains",
                        },
                        {"type": "person", "key": "another_key", "value": "value"},
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertCountEqual(results, [p1_uuid])

        def test_boolean_filters_persons(self):
            p1_uuid = str(
                person_factory(
                    team_id=self.team.pk,
                    distinct_ids=["p1"],
                    properties={"is_first_user": True},
                ).uuid
            )
            person_factory(team_id=self.team.pk, distinct_ids=["p2"])

            filter = Filter(data={"properties": [{"type": "person", "key": "is_first_user", "value": ["true"]}]})
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p1_uuid])

        def test_is_not_set_and_is_set_persons(self):
            p1_uuid = str(
                person_factory(
                    team_id=self.team.pk,
                    distinct_ids=["p1"],
                    properties={"is_first_user": True},
                ).uuid
            )
            p2_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p2"]).uuid)

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "is_first_user",
                            "value": "",
                            "operator": "is_set",
                        }
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p1_uuid])

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "is_first_user",
                            "value": "",
                            "operator": "is_not_set",
                        }
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p2_uuid])

        def test_is_not_true_false_persons(self):
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["p1"],
                properties={"is_first_user": True},
            )
            p2_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p2"]).uuid)

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "is_first_user",
                            "value": ["true"],
                            "operator": "is_not",
                        }
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p2_uuid])

        def test_is_date_before_persons(self):
            p1_uuid = str(
                person_factory(
                    team_id=self.team.pk,
                    distinct_ids=["p1"],
                    properties={"some-timestamp": "2022-03-01"},
                ).uuid
            )
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["p2"],
                properties={"some-timestamp": "2022-05-01"},
            )

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "some-timestamp",
                            "value": "2022-04-01",
                            "operator": "is_date_before",
                        }
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p1_uuid])

        def test_json_object(self):
            p1_uuid = person_factory(
                team_id=self.team.pk,
                distinct_ids=["person1"],
                properties={"name": {"first_name": "Mary", "last_name": "Smith"}},
            )
            filter = Filter(
                data={
                    "properties": [
                        {
                            "key": "name",
                            "value": json.dumps({"first_name": "Mary", "last_name": "Smith"}),
                            "type": "person",
                        }
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [str(p1_uuid.uuid)])

        def test_filter_out_team_members_persons(self):
            person_factory(
                team_id=self.team.pk,
                distinct_ids=["team_member"],
                properties={"email": "test@posthog.com"},
            )
            p2_uuid = str(
                person_factory(
                    team_id=self.team.pk,
                    distinct_ids=["random_user"],
                    properties={"email": "test@gmail.com"},
                ).uuid
            )
            self.team.test_account_filters = [
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                }
            ]
            self.team.save()
            filter = Filter(data={FILTER_TEST_ACCOUNTS: True}, team=self.team)

            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p2_uuid])

    return TestPropertiesToQ


def _filter_persons(filter: Filter, team: Team):
    flush_persons_and_events()
    persons = Person.objects.filter(properties_to_Q(team.pk, filter.property_groups.flat))
    persons = persons.filter(team_id=team.pk)
    return [str(uuid) for uuid in persons.values_list("uuid", flat=True)]


class TestDjangoPropertiesToQ(property_to_Q_test_factory(_filter_persons, _create_person), QueryMatchingTest):  # type: ignore
    @snapshot_postgres_queries
    def test_array_property_as_string_on_persons(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["person1"],
            properties={"urls": ["https://whatever.com", '["abcd"]', "efg"]},
        )
        Person.objects.create(team=self.team, distinct_ids=["person2"], properties={"urls": ['["abcd"]']})
        Person.objects.create(team=self.team, distinct_ids=["person3"], properties={"urls": '["abcd"]'})
        Person.objects.create(team=self.team, distinct_ids=["person4"], properties={"urls": "['abcd']"})
        Person.objects.create(team=self.team, distinct_ids=["person5"])

        # some idiosyncracies on how this works, but we shouldn't error out on this
        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "person",
                        "key": "urls",
                        "operator": "icontains",
                        "value": '["abcd"]',
                    }
                ]
            }
        )

        persons = Person.objects.filter(property_group_to_Q(self.team.pk, filter.property_groups))
        persons = persons.filter(team_id=self.team.pk)
        results = sorted([person.distinct_ids[0] for person in persons])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], "person3")

    def test_person_cohort_properties(self):
        person1_distinct_id = "person1"
        person1 = Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"$some_prop": 1},
        )
        cohort1 = Cohort.objects.create(team=self.team, groups=[{"properties": {"$some_prop": 1}}], name="cohort1")
        cohort1.people.add(person1)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]})

        with self.assertNumQueries(2):
            matched_person = (
                Person.objects.filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
        self.assertTrue(matched_person)

    def test_person_cohort_properties_with_zero_value(self):
        person1_distinct_id = "person1"
        person1 = Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"$some_prop": 0},
        )
        cohort1 = Cohort.objects.create(team=self.team, groups=[{"properties": {"$some_prop": 0}}], name="cohort1")
        cohort1.people.add(person1)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]})

        with self.assertNumQueries(2):
            matched_person = (
                Person.objects.filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
        self.assertTrue(matched_person)

    def test_person_cohort_properties_with_negation(self):
        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"$some_prop": "matches"},
        )

        user_in = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "matches",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="user_in_this_cohort",
        )
        not_in_1_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$bad_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                            ],
                        },
                    ],
                }
            },
            name="user_not_in_1",
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "id",
                            "negation": False,
                            "type": "cohort",
                            "value": user_in.pk,
                        },
                        {
                            "key": "id",
                            "negation": True,
                            "type": "cohort",
                            "value": not_in_1_cohort.pk,
                        },
                    ],
                }
            },
            name="overall_cohort",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]})

        with self.assertNumQueries(4):
            matched_person = (
                Person.objects.filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
        self.assertTrue(matched_person)

    def test_group_property_filters_direct(self):
        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "some_prop",
                        "value": 5,
                        "type": "group",
                        "group_type_index": 1,
                    }
                ]
            }
        )
        query_filter = properties_to_Q(self.team.pk, filter.property_groups.flat)
        self.assertEqual(
            query_filter,
            Q(
                Q(group_properties__some_prop=5)
                & Q(group_properties__has_key="some_prop")
                & ~Q(group_properties__some_prop=None)
            ),
        )

    def test_person_relative_date_parsing(self):
        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"created_at": "2021-04-04T12:00:00Z"},
        )
        filter = Filter(
            data={"properties": [{"key": "created_at", "value": "2d", "type": "person", "operator": "is_date_after"}]}
        )

        with self.assertNumQueries(1), freeze_time("2021-04-06T10:00:00"):
            matched_person = (
                Person.objects.filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
        self.assertTrue(matched_person)

    def test_person_matching_greater_than_filter(self):
        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"registration_ts": 5},
        )
        filter = Filter(
            data={"properties": [{"key": "registration_ts", "value": "4", "type": "person", "operator": "gt"}]}
        )

        with self.assertNumQueries(1):
            matched_person = (
                Person.objects.annotate(
                    **{
                        "properties_registrationts_68f210b8c014e1b_type": Func(
                            F("properties__registration_ts"),
                            function="JSONB_TYPEOF",
                            output_field=CharField(),
                        )
                    }
                )
                .filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
        self.assertTrue(matched_person)

    def test_broken_person_filter_never_matching(self):
        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"registration_ts": 1716447600},
        )
        # This broken filter came from this issue: https://github.com/PostHog/posthog/issues/23213
        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                # This is the valid condition
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": "1716274800",
                                    "negation": False,
                                    "operator": "gte",
                                },
                                # This is the invalid condition (lte operator comparing against a list of values)
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": ["1716447600"],
                                    "negation": False,
                                    "operator": "lte",
                                },
                            ],
                        }
                    ],
                }
            }
        )

        with self.assertNumQueries(1):
            matched_person = (
                Person.objects.annotate(
                    **{
                        "properties_registrationts_68f210b8c014e1b_type": Func(
                            F("properties__registration_ts"),
                            function="JSONB_TYPEOF",
                            output_field=CharField(),
                        )
                    }
                )
                .filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
        # This shouldn't pass because we have an AND condition with a broken lte operator
        # (we should never have a lte operator comparing against a list of values)
        # So this should never match
        self.assertFalse(matched_person)

    def test_broken_condition_does_not_break_entire_filter(self):
        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"registration_ts": 1716447600},
        )
        # Create a cohort with an OR filter that has an invalid condition
        # (a lte operator comparing against a list of values)
        # This should still evaluate to True, though, because the other condition is valid
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test OR Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            # This is the valid condition
                            "values": [
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": "1716274800",
                                    "negation": False,
                                    "operator": "gte",
                                },
                                # This is the invalid condition
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": ["1716447600"],
                                    "negation": False,
                                    "operator": "lte",
                                },
                            ],
                        }
                    ],
                }
            },
        )
        filter = Filter(data={"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]})
        with self.assertNumQueries(2):
            matched_person = (
                Person.objects.annotate(
                    **{
                        "properties_registrationts_68f210b8c014e1b_type": Func(
                            F("properties__registration_ts"),
                            function="JSONB_TYPEOF",
                            output_field=CharField(),
                        )
                    }
                )
                .filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
        # This should now pass because the cohort filter still has one valid condition
        self.assertTrue(matched_person)

    def test_person_matching_real_filter(self):
        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"registration_ts": 1716447600},
        )
        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": "1716274800",
                                    "negation": False,
                                    "operator": "gt",
                                },
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": ["1716447600"],
                                    "negation": False,
                                    "operator": "exact",
                                },
                            ],
                        }
                    ],
                }
            }
        )
        with self.assertNumQueries(1):
            matched_person = (
                Person.objects.annotate(
                    **{
                        "properties_registrationts_68f210b8c014e1b_type": Func(
                            F("properties__registration_ts"),
                            function="JSONB_TYPEOF",
                            output_field=CharField(),
                        )
                    }
                )
                .filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
        self.assertTrue(matched_person)

    def test_person_relative_date_parsing_with_override_property(self):
        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"created_at": "2021-04-04T12:00:00Z"},
        )
        filter = Filter(
            data={"properties": [{"key": "created_at", "value": "2m", "type": "person", "operator": "is_date_after"}]}
        )

        with self.assertNumQueries(1):
            matched_person = (
                Person.objects.filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(
                    properties_to_Q(
                        self.team.pk,
                        filter.property_groups.flat,
                        override_property_values={"created_at": "2022-10-06T10:00:00Z"},
                    )
                )
                .exists()
            )
        self.assertFalse(matched_person)

    @freeze_time("2021-04-06T10:00:00")
    def test_person_relative_date_parsing_with_invalid_date(self):
        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"created_at": "2021-04-04T12:00:00Z"},
        )
        filter = Filter(
            data={
                "properties": [
                    {"key": "created_at", "value": ["2m", "3d"], "type": "person", "operator": "is_date_after"}
                ]
            }
        )

        with snapshot_postgres_queries_context(self):
            matched_person = (
                Person.objects.filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
            # needs an exact match
            self.assertFalse(matched_person)

        filter = Filter(
            data={
                "properties": [{"key": "created_at", "value": "bazinga", "type": "person", "operator": "is_date_after"}]
            }
        )

        with snapshot_postgres_queries_context(self):
            matched_person = (
                Person.objects.filter(
                    team_id=self.team.pk,
                    persondistinctid__distinct_id=person1_distinct_id,
                )
                .filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
                .exists()
            )
            self.assertFalse(matched_person)

    def _filter_with_date_range(
        self, date_from: datetime.datetime, date_to: Optional[datetime.datetime] = None
    ) -> Filter:
        data = {
            "properties": [{"key": "some_prop", "value": 5, "type": "group", "group_type_index": 1}],
            "date_from": date_from,
        }
        if date_to:
            data["date_to"] = date_to

        return Filter(data=data)

    def test_numerical_person_properties(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"$a_number": 4})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"$a_number": 5})
        _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"$a_number": 6})
        _create_person(team_id=self.team.pk, distinct_ids=["p4"], properties={"$a_number": 14})

        flush_persons_and_events()

        def filter_persons_with_annotation(filter: Filter, team: Team):
            persons = Person.objects.annotate(
                **{
                    "properties_anumber_27b11200b8ed4fb_type": Func(
                        F("properties__$a_number"), function="JSONB_TYPEOF", output_field=CharField()
                    )
                }
            ).filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
            persons = persons.filter(team_id=team.pk)
            return [str(uuid) for uuid in persons.values_list("uuid", flat=True)]

        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "person",
                        "key": "$a_number",
                        "value": "4",
                        "operator": "gt",
                    }
                ]
            }
        )
        self.assertEqual(len(filter_persons_with_annotation(filter, self.team)), 3)

        filter = Filter(data={"properties": [{"type": "person", "key": "$a_number", "value": 5}]})
        self.assertEqual(len(filter_persons_with_annotation(filter, self.team)), 1)

        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "person",
                        "key": "$a_number",
                        "value": 6,
                        "operator": "lt",
                    }
                ]
            }
        )
        self.assertEqual(len(filter_persons_with_annotation(filter, self.team)), 2)

    @snapshot_postgres_queries
    def test_icontains_with_array_value(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"$key": "red-123"})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"$key": "blue-123"})
        _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"$key": 6})

        flush_persons_and_events()

        def filter_persons_with_annotation(filter: Filter, team: Team):
            persons = Person.objects.annotate(
                **{
                    "properties_$key_type": Func(
                        F("properties__$key"), function="JSONB_TYPEOF", output_field=CharField()
                    )
                }
            ).filter(properties_to_Q(self.team.pk, filter.property_groups.flat))
            persons = persons.filter(team_id=team.pk)
            return [str(uuid) for uuid in persons.values_list("uuid", flat=True)]

        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "person",
                        "key": "$key",
                        "value": ["red"],
                        "operator": "icontains",
                    }
                ]
            }
        )
        self.assertEqual(len(filter_persons_with_annotation(filter, self.team)), 0)

        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "person",
                        "key": "$key",
                        "value": "red",
                        "operator": "icontains",
                    }
                ]
            }
        )
        self.assertEqual(len(filter_persons_with_annotation(filter, self.team)), 1)


def filter_persons_with_property_group(
    filter: Filter, team: Team, property_overrides: Optional[dict[str, Any]] = None
) -> list[str]:
    if property_overrides is None:
        property_overrides = {}
    flush_persons_and_events()
    persons = Person.objects.filter(property_group_to_Q(team.pk, filter.property_groups, property_overrides))
    persons = persons.filter(team_id=team.pk)
    return sorted([person.distinct_ids[0] for person in persons])


class TestDjangoPropertyGroupToQ(BaseTest, QueryMatchingTest):
    def test_simple_property_group_to_q(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"url": "https://whatever.com"},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"url": 1})
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"url": {"bla": "bla"}},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": "https://whatever.com",
                        },
                        {"type": "person", "key": "url", "value": 1},
                    ],
                }
            }
        )

        results = filter_persons_with_property_group(filter, self.team)
        self.assertEqual(len(results), 2)
        self.assertEqual(["person1", "person2"], results)

    def test_multiple_properties_property_group_to_q(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"url": "https://whatever.com", "bla": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"url": 1, "bla": 2},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"url": {"bla": "bla"}, "bla": 3},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "person",
                            "key": "url",
                            "value": "https://whatever.com",
                        },
                        {"type": "person", "key": "bla", "value": 1},
                    ],
                }
            }
        )

        results = filter_persons_with_property_group(filter, self.team)
        self.assertEqual(len(results), 1)
        self.assertEqual(["person1"], results)

    def test_nested_property_group_to_q(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"url": "https://whatever.com", "bla": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"url": 1, "bla": 2},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"url": {"bla": "bla"}, "bla": 3},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "url",
                                    "value": "https://whatever.com",
                                },
                                {"type": "person", "key": "bla", "value": 1},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"type": "person", "key": "bla", "value": 3}],
                        },
                    ],
                }
            }
        )

        results = filter_persons_with_property_group(filter, self.team)
        self.assertEqual(len(results), 2)
        self.assertEqual(["person1", "person3"], results)

    def test_property_group_to_q_with_property_overrides(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"url": "https://whatever.com", "bla": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"url": 1, "bla": 2},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"url": {"bla": "bla"}, "bla": 3},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "url",
                                    "value": "https://whatever.com",
                                },
                                {"type": "person", "key": "bla", "value": 1},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"type": "person", "key": "bla", "value": 3}],
                        },
                    ],
                }
            }
        )

        results = filter_persons_with_property_group(filter, self.team, {"bla": 2})
        # all discarded because bla is neither 1 nor 3
        self.assertEqual(len(results), 0)

    @snapshot_postgres_queries
    def test_property_group_to_q_with_cohorts(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"url": "https://whatever.com", "bla": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"url": 1, "bla": 2},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"url": {"bla": "bla"}, "bla": 3},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "person", "key": "bla", "value": 1},
                        {"type": "person", "key": "bla", "value": 2},
                    ],
                }
            },
            name="cohort1",
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "url",
                                    "value": "https://whatever.com",
                                },
                                {"type": "person", "key": "bla", "value": 1},
                                {"type": "cohort", "key": "id", "value": cohort1.pk},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"type": "person", "key": "bla", "value": 3}],
                        },
                    ],
                }
            }
        )

        results = filter_persons_with_property_group(filter, self.team)
        self.assertEqual(len(results), 2)
        self.assertEqual(["person1", "person3"], results)

    @snapshot_postgres_queries
    def test_property_group_to_q_with_negation_cohorts(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"bla": 1, "other": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"bla": 2, "other": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"bla": 3, "other": 2},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person4"],
            properties={"bla": 4, "other": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person5"],
            properties={"bla": 5, "other": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person6"],
            properties={"bla": 6, "other": 1},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "person", "key": "bla", "value": 1},
                        {"type": "person", "key": "bla", "value": 2},
                    ],
                }
            },
            name="cohort1",
        )

        cohort2 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "person", "key": "bla", "value": 3},
                        {"type": "person", "key": "bla", "value": 4},
                    ],
                }
            },
            name="cohort2",
        )

        cohort3 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "person", "key": "other", "value": 1},
                    ],
                }
            },
            name="cohort3",
        )

        cohort4 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "cohort",
                            "key": "id",
                            "value": cohort1.pk,
                            "negation": True,
                        },
                        {
                            "type": "cohort",
                            "key": "id",
                            "value": cohort2.pk,
                            "negation": True,
                        },
                        {"type": "cohort", "key": "id", "value": cohort3.pk},
                    ],
                }
            },
            name="cohort2",
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "cohort", "key": "id", "value": cohort4.pk},
                    ],
                }
            }
        )

        results = filter_persons_with_property_group(filter, self.team)
        self.assertEqual(len(results), 2)
        self.assertEqual(["person5", "person6"], results)

    @snapshot_postgres_queries
    def test_property_group_to_q_with_cohorts_no_match(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"url": "https://whatever.com", "bla": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"url": 1, "bla": 2},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"url": {"bla": "bla"}, "bla": 3},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "key": "bla", "value": 1},
                        {"type": "person", "key": "bla", "value": 2},
                    ],
                }
            },
            name="cohort1",
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "url",
                                    "value": "https://whatever.com",
                                },
                                {"type": "person", "key": "bla", "value": 1},
                                {"type": "cohort", "key": "id", "value": cohort1.pk},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"type": "person", "key": "bla", "value": 3}],
                        },
                    ],
                }
            }
        )

        results = filter_persons_with_property_group(filter, self.team)
        self.assertEqual(len(results), 1)
        self.assertEqual(["person3"], results)

    def test_property_group_to_q_with_behavioural_cohort(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"url": "https://whatever.com", "bla": 1},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"url": 1, "bla": 2},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"url": {"bla": "bla"}, "bla": 3},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"event_id": "$pageview", "days": 7}],
            name="cohort2",
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "url",
                                    "value": "https://whatever.com",
                                },
                                {"type": "person", "key": "bla", "value": 1},
                                {"type": "cohort", "key": "id", "value": cohort2.pk},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"type": "person", "key": "bla", "value": 3}],
                        },
                    ],
                }
            }
        )

        with self.assertRaises(ValueError):
            filter_persons_with_property_group(filter, self.team)
