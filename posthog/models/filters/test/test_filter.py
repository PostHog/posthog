import json
from typing import Callable, cast

from django.db.models import Q

from posthog.constants import FILTER_TEST_ACCOUNTS
from posthog.models import Cohort, Filter, Person, Team
from posthog.models.property import Property
from posthog.queries.base import properties_to_Q
from posthog.test.base import BaseTest, _create_person, flush_persons_and_events


class TestFilter(BaseTest):
    def test_old_style_properties(self):
        filter = Filter(data={"properties": {"$browser__is_not": "IE7", "$OS": "Mac",}})
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
            ],
        )

    def test_simplify_test_accounts(self):
        self.team.test_account_filters = [
            {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}
        ]
        self.team.save()

        data = {"properties": [{"key": "attr", "value": "some_val"}]}

        filter = Filter(data=data, team=self.team)

        self.assertEqual(
            filter.properties_to_dict(),
            {"properties": {"type": "AND", "values": [{"key": "attr", "value": "some_val", "type": "event"},],},},
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
                                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}
                            ],
                        },
                        {"type": "AND", "values": [{"key": "attr", "value": "some_val", "type": "event"}],},
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
                                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}
                            ],
                        },
                        {"type": "AND", "values": [{"key": "attr", "value": "some_val", "type": "event"}],},
                    ],
                }
            },
        )


def property_to_Q_test_factory(filter_persons: Callable, person_factory):
    class TestPropertiesToQ(BaseTest):
        def test_simple_persons(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person1"], properties={"url": "https://whatever.com"})
            person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"url": 1})
            person_factory(team_id=self.team.pk, distinct_ids=["person3"], properties={"url": {"bla": "bla"}})
            person_factory(team_id=self.team.pk, distinct_ids=["person4"])

            filter = Filter(data={"properties": [{"type": "person", "key": "url", "value": "https://whatever.com"}]})

            results = filter_persons(filter, self.team)
            self.assertEqual(len(results), 1)

        def test_multiple_equality_persons(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person1"], properties={"url": "https://whatever.com"})
            person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"url": 1})
            person_factory(team_id=self.team.pk, distinct_ids=["person3"], properties={"url": {"bla": "bla"}})
            person_factory(team_id=self.team.pk, distinct_ids=["person4"])
            person_factory(team_id=self.team.pk, distinct_ids=["person5"], properties={"url": "https://example.com"})

            filter = Filter(
                data={
                    "properties": [
                        {"type": "person", "key": "url", "value": ["https://whatever.com", "https://example.com"]}
                    ]
                }
            )

            results = filter_persons(filter, self.team)
            self.assertEqual(len(results), 2)

        def test_incomplete_data(self):
            filter = Filter(
                data={"properties": [{"key": "$current_url", "operator": "not_icontains", "type": "event"}]}
            )
            self.assertListEqual(filter.property_groups.values, [])

        def test_numerical_person_properties(self):
            person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"$a_number": 4})
            person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"$a_number": 5})
            person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"$a_number": 6})

            filter = Filter(data={"properties": [{"type": "person", "key": "$a_number", "value": 4, "operator": "gt"}]})
            self.assertEqual(len(filter_persons(filter, self.team)), 2)

            filter = Filter(data={"properties": [{"type": "person", "key": "$a_number", "value": 5}]})
            self.assertEqual(len(filter_persons(filter, self.team)), 1)

            filter = Filter(data={"properties": [{"type": "person", "key": "$a_number", "value": 6, "operator": "lt"}]})
            self.assertEqual(len(filter_persons(filter, self.team)), 2)

        def test_contains_persons(self):
            person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"url": "https://whatever.com"})
            person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"url": "https://example.com"})

            filter = Filter(
                data={"properties": [{"type": "person", "key": "url", "value": "whatever", "operator": "icontains"}]}
            )

            results = filter_persons(filter, self.team)
            self.assertEqual(len(results), 1)

        def test_regex_persons(self):
            p1_uuid = str(
                person_factory(
                    team_id=self.team.pk, distinct_ids=["p1"], properties={"url": "https://whatever.com"}
                ).uuid
            )
            p2_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p2"]).uuid)

            filter = Filter(
                data={"properties": [{"type": "person", "key": "url", "value": r"\.com$", "operator": "regex"}]}
            )
            results = filter_persons(filter, self.team)
            self.assertCountEqual(results, [p1_uuid])

            filter = Filter(
                data={"properties": [{"type": "person", "key": "url", "value": r"\.eee$", "operator": "not_regex"}]}
            )
            results = filter_persons(filter, self.team)
            self.assertCountEqual(results, [p1_uuid, p2_uuid])

        def test_invalid_regex_persons(self):
            person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"url": "https://whatever.com"})
            person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"url": "https://example.com"})

            filter = Filter(
                data={"properties": [{"type": "person", "key": "url", "value": r"?*", "operator": "regex"}]}
            )
            self.assertEqual(len(filter_persons(filter, self.team)), 0)

            filter = Filter(
                data={"properties": [{"type": "person", "key": "url", "value": r"?*", "operator": "not_regex"}]}
            )
            self.assertEqual(len(filter_persons(filter, self.team)), 0)

        def test_is_not_persons(self):
            person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"url": "https://whatever.com"})
            p2_uuid = str(
                person_factory(
                    team_id=self.team.pk, distinct_ids=["p2"], properties={"url": "https://example.com"}
                ).uuid
            )

            filter = Filter(
                data={
                    "properties": [
                        {"type": "person", "key": "url", "value": "https://whatever.com", "operator": "is_not"}
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertCountEqual(results, [p2_uuid])

        def test_does_not_contain_persons(self):
            person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"url": "https://whatever.com"})
            p2_uuid = str(
                person_factory(
                    team_id=self.team.pk, distinct_ids=["p2"], properties={"url": "https://example.com"}
                ).uuid
            )
            p3_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p3"]).uuid)
            p4_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"url": None}).uuid)

            filter = Filter(
                data={
                    "properties": [
                        {"type": "person", "key": "url", "value": "whatever.com", "operator": "not_icontains"}
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
            person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"url": "https://whatever.com"})

            filter = Filter(
                data={
                    "properties": [
                        {"type": "person", "key": "url", "value": "whatever.com", "operator": "icontains"},
                        {"type": "person", "key": "another_key", "value": "value"},
                    ]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertCountEqual(results, [p1_uuid])

        def test_boolean_filters_persons(self):
            p1_uuid = str(
                person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"is_first_user": True}).uuid
            )
            person_factory(team_id=self.team.pk, distinct_ids=["p2"])

            filter = Filter(data={"properties": [{"type": "person", "key": "is_first_user", "value": ["true"]}]})
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p1_uuid])

        def test_is_not_set_and_is_set_persons(self):
            p1_uuid = str(
                person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"is_first_user": True}).uuid
            )
            p2_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p2"]).uuid)

            filter = Filter(
                data={"properties": [{"type": "person", "key": "is_first_user", "value": "", "operator": "is_set"}]}
            )
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p1_uuid])

            filter = Filter(
                data={"properties": [{"type": "person", "key": "is_first_user", "value": "", "operator": "is_not_set"}]}
            )
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p2_uuid])

        def test_is_not_true_false_persons(self):
            person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"is_first_user": True})
            p2_uuid = str(person_factory(team_id=self.team.pk, distinct_ids=["p2"]).uuid)

            filter = Filter(
                data={
                    "properties": [{"type": "person", "key": "is_first_user", "value": ["true"], "operator": "is_not"}]
                }
            )
            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p2_uuid])

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
            person_factory(team_id=self.team.pk, distinct_ids=["team_member"], properties={"email": "test@posthog.com"})
            p2_uuid = str(
                person_factory(
                    team_id=self.team.pk, distinct_ids=["random_user"], properties={"email": "test@gmail.com"}
                ).uuid
            )
            self.team.test_account_filters = [
                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}
            ]
            self.team.save()
            filter = Filter(data={FILTER_TEST_ACCOUNTS: True}, team=self.team)

            results = filter_persons(filter, self.team)
            self.assertEqual(results, [p2_uuid])

    return TestPropertiesToQ


def _filter_persons(filter: Filter, team: Team):
    flush_persons_and_events()
    # TODO: confirm what to do here?
    # Postgres only supports ANDing all properties :shrug:
    persons = Person.objects.filter(properties_to_Q(filter.property_groups.flat, team_id=team.pk, is_direct_query=True))
    persons = persons.filter(team_id=team.pk)
    return [str(uuid) for uuid in persons.values_list("uuid", flat=True)]


class TestDjangoPropertiesToQ(property_to_Q_test_factory(_filter_persons, _create_person)):  # type: ignore
    def test_person_cohort_properties(self):
        person1_distinct_id = "person1"
        person1 = Person.objects.create(
            team=self.team, distinct_ids=[person1_distinct_id], properties={"$some_prop": 1}
        )
        cohort1 = Cohort.objects.create(team=self.team, groups=[{"properties": {"$some_prop": 1}}], name="cohort1")
        cohort1.people.add(person1)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})

        matched_person = (
            Person.objects.filter(team_id=self.team.pk, persondistinctid__distinct_id=person1_distinct_id)
            .filter(properties_to_Q(filter.property_groups.flat, team_id=self.team.pk, is_direct_query=True))
            .exists()
        )
        self.assertTrue(matched_person)

    def test_group_property_filters_direct(self):
        filter = Filter(data={"properties": [{"key": "some_prop", "value": 5, "type": "group", "group_type_index": 1}]})
        query_filter = properties_to_Q(filter.property_groups.flat, team_id=self.team.pk, is_direct_query=True)

        self.assertEqual(query_filter, Q(group_properties__some_prop=5))

    def test_group_property_filters_used(self):
        filter = Filter(data={"properties": [{"key": "some_prop", "value": 5, "type": "group", "group_type_index": 1}]})
        self.assertRaises(ValueError, lambda: properties_to_Q(filter.property_groups.flat, team_id=self.team.pk))
