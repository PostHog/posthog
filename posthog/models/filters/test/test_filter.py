import datetime
import json
from typing import Any, Callable, Dict, List, Optional, cast

from django.db.models import Q

from posthog.constants import FILTER_TEST_ACCOUNTS
from posthog.models import Cohort, Filter, Person, Team
from posthog.models.property import Property
from posthog.queries.base import properties_to_Q, property_group_to_Q
from posthog.test.base import (
    BaseTest,
    QueryMatchingTest,
    _create_person,
    flush_persons_and_events,
    snapshot_postgres_queries,
)


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

        def test_numerical_person_properties(self):
            person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"$a_number": 4})
            person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"$a_number": 5})
            person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"$a_number": 6})

            filter = Filter(
                data={
                    "properties": [
                        {
                            "type": "person",
                            "key": "$a_number",
                            "value": 4,
                            "operator": "gt",
                        }
                    ]
                }
            )
            self.assertEqual(len(filter_persons(filter, self.team)), 2)

            filter = Filter(data={"properties": [{"type": "person", "key": "$a_number", "value": 5}]})
            self.assertEqual(len(filter_persons(filter, self.team)), 1)

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
            self.assertEqual(len(filter_persons(filter, self.team)), 2)

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
    persons = Person.objects.filter(properties_to_Q(filter.property_groups.flat))
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

        persons = Person.objects.filter(property_group_to_Q(filter.property_groups))
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
                .filter(properties_to_Q(filter.property_groups.flat))
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
                .filter(properties_to_Q(filter.property_groups.flat))
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
                .filter(properties_to_Q(filter.property_groups.flat))
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
        query_filter = properties_to_Q(filter.property_groups.flat)
        self.assertEqual(
            query_filter,
            Q(
                Q(group_properties__some_prop=5)
                & Q(group_properties__has_key="some_prop")
                & ~Q(group_properties__some_prop=None)
            ),
        )

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


def filter_persons_with_property_group(
    filter: Filter, team: Team, property_overrides: Dict[str, Any] = {}
) -> List[str]:
    flush_persons_and_events()
    persons = Person.objects.filter(property_group_to_Q(filter.property_groups, property_overrides))
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
