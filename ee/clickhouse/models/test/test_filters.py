import json
from typing import Optional

from posthog.test.base import ClickhouseTestMixin, _create_event, _create_person

from posthog.clickhouse.client import query_with_columns, sync_execute
from posthog.constants import FILTER_TEST_ACCOUNTS
from posthog.models import Element, Organization, Person, Team
from posthog.models.cohort import Cohort
from posthog.models.event.sql import GET_EVENTS_WITH_PROPERTIES
from posthog.models.event.util import ClickhouseEventSerializer
from posthog.models.filters import Filter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.test.test_filter import (
    TestFilter as PGTestFilters,
    property_to_Q_test_factory,
)
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.queries.util import PersonPropertiesMode
from posthog.test.test_journeys import journeys_for


def _filter_events(filter: Filter, team: Team, order_by: Optional[str] = None):
    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        property_group=filter.property_groups,
        team_id=team.pk,
        hogql_context=filter.hogql_context,
    )
    params = {"team_id": team.pk, **prop_filter_params}

    events = query_with_columns(
        GET_EVENTS_WITH_PROPERTIES.format(
            filters=prop_filters,
            order_by="ORDER BY {}".format(order_by) if order_by else "",
        ),
        params,
    )
    parsed_events = ClickhouseEventSerializer(events, many=True, context={"elements": None, "people": None}).data
    return parsed_events


def _filter_persons(filter: Filter, team: Team):
    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        property_group=filter.property_groups,
        team_id=team.pk,
        person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
        hogql_context=filter.hogql_context,
    )
    # Note this query does not handle person rows changing over time
    rows = sync_execute(
        f"SELECT id, properties AS person_props FROM person WHERE team_id = %(team_id)s {prop_filters}",
        {"team_id": team.pk, **prop_filter_params, **filter.hogql_context.values},
    )
    return [str(uuid) for uuid, _ in rows]


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


class TestFiltering(ClickhouseTestMixin, property_to_Q_test_factory(_filter_persons, _create_person)):  # type: ignore
    def test_simple(self):
        _create_event(team=self.team, distinct_id="test", event="$pageview")
        _create_event(
            team=self.team,
            distinct_id="test",
            event="$pageview",
            properties={"$current_url": 1},
        )  # test for type incompatibility
        _create_event(
            team=self.team,
            distinct_id="test",
            event="$pageview",
            properties={"$current_url": {"bla": "bla"}},
        )  # test for type incompatibility
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://whatever.com"},
        )
        filter = Filter(data={"properties": {"$current_url": "https://whatever.com"}})
        events = _filter_events(filter, self.team)
        self.assertEqual(len(events), 1)

    def test_multiple_equality(self):
        _create_event(team=self.team, distinct_id="test", event="$pageview")
        _create_event(
            team=self.team,
            distinct_id="test",
            event="$pageview",
            properties={"$current_url": 1},
        )  # test for type incompatibility
        _create_event(
            team=self.team,
            distinct_id="test",
            event="$pageview",
            properties={"$current_url": {"bla": "bla"}},
        )  # test for type incompatibility
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://whatever.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://example.com"},
        )
        filter = Filter(data={"properties": {"$current_url": ["https://whatever.com", "https://example.com"]}})
        events = _filter_events(filter, self.team)
        self.assertEqual(len(events), 2)

    def test_numerical(self):
        event1_uuid = _create_event(
            team=self.team,
            distinct_id="test",
            event="$pageview",
            properties={"$a_number": 5},
        )
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$a_number": 6},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$a_number": "rubbish"},
        )
        filter = Filter(data={"properties": {"$a_number__gt": 5}})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event2_uuid)

        filter = Filter(data={"properties": {"$a_number": 5}})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event1_uuid)

        filter = Filter(data={"properties": {"$a_number__lt": 6}})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event1_uuid)

    def test_numerical_person_properties(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"$a_number": 4})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"$a_number": 5})
        _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"$a_number": 6})

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
        self.assertEqual(len(_filter_persons(filter, self.team)), 2)

        filter = Filter(data={"properties": [{"type": "person", "key": "$a_number", "value": 5}]})
        self.assertEqual(len(_filter_persons(filter, self.team)), 1)

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
        self.assertEqual(len(_filter_persons(filter, self.team)), 2)

    def test_contains(self):
        _create_event(team=self.team, distinct_id="test", event="$pageview")
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://whatever.com"},
        )
        filter = Filter(data={"properties": {"$current_url__icontains": "whatever"}})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event2_uuid)

    def test_regex(self):
        event1_uuid = _create_event(team=self.team, distinct_id="test", event="$pageview")
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://whatever.com"},
        )
        filter = Filter(data={"properties": {"$current_url__regex": r"\.com$"}})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event2_uuid)

        filter = Filter(data={"properties": {"$current_url__not_regex": r"\.eee$"}})
        events = _filter_events(filter, self.team, order_by="timestamp")
        self.assertEqual(events[0]["id"], event1_uuid)
        self.assertEqual(events[1]["id"], event2_uuid)

    def test_invalid_regex(self):
        _create_event(team=self.team, distinct_id="test", event="$pageview")
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://whatever.com"},
        )

        filter = Filter(data={"properties": {"$current_url__regex": "?*"}})
        self.assertEqual(len(_filter_events(filter, self.team)), 0)

        filter = Filter(data={"properties": {"$current_url__not_regex": "?*"}})
        self.assertEqual(len(_filter_events(filter, self.team)), 0)

    def test_is_not(self):
        event1_uuid = _create_event(team=self.team, distinct_id="test", event="$pageview")
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://something.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://whatever.com"},
        )
        filter = Filter(data={"properties": {"$current_url__is_not": "https://whatever.com"}})
        events = _filter_events(filter, self.team)
        self.assertEqual(
            sorted([events[0]["id"], events[1]["id"]]),
            sorted([event1_uuid, event2_uuid]),
        )
        self.assertEqual(len(events), 2)

    def test_does_not_contain(self):
        event1_uuid = _create_event(team=self.team, event="$pageview", distinct_id="test")
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://something.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://whatever.com"},
        )
        event3_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": None},
        )
        filter = Filter(data={"properties": {"$current_url__not_icontains": "whatever.com"}})
        events = _filter_events(filter, self.team)
        self.assertCountEqual([event["id"] for event in events], [event1_uuid, event2_uuid, event3_uuid])
        self.assertEqual(len(events), 3)

    def test_multiple(self):
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={
                "$current_url": "https://something.com",
                "another_key": "value",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"$current_url": "https://something.com"},
        )
        filter = Filter(
            data={
                "properties": {
                    "$current_url__icontains": "something.com",
                    "another_key": "value",
                }
            }
        )
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event2_uuid)
        self.assertEqual(len(events), 1)

    def test_user_properties(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"group": "some group"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"group": "another group"},
        )
        event2_uuid = _create_event(
            team=self.team,
            distinct_id="person1",
            event="$pageview",
            properties={
                "$current_url": "https://something.com",
                "another_key": "value",
            },
        )
        event_p2_uuid = _create_event(
            team=self.team,
            distinct_id="person2",
            event="$pageview",
            properties={"$current_url": "https://something.com"},
        )

        # test for leakage
        _, _, team2 = Organization.objects.bootstrap(None)
        _create_person(
            team_id=team2.pk,
            distinct_ids=["person_team_2"],
            properties={"group": "another group"},
        )
        _create_event(
            team=team2,
            distinct_id="person_team_2",
            event="$pageview",
            properties={
                "$current_url": "https://something.com",
                "another_key": "value",
            },
        )

        filter = Filter(data={"properties": [{"key": "group", "value": "some group", "type": "person"}]})
        events = _filter_events(filter=filter, team=self.team, order_by=None)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], event2_uuid)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "group",
                        "operator": "is_not",
                        "value": "some group",
                        "type": "person",
                    }
                ]
            }
        )
        events = _filter_events(filter=filter, team=self.team, order_by=None)
        self.assertEqual(events[0]["id"], event_p2_uuid)
        self.assertEqual(len(events), 1)

    def test_user_properties_numerical(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"group": 1})
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"group": 2})
        event2_uuid = _create_event(
            team=self.team,
            distinct_id="person1",
            event="$pageview",
            properties={
                "$current_url": "https://something.com",
                "another_key": "value",
            },
        )
        _create_event(
            team=self.team,
            distinct_id="person2",
            event="$pageview",
            properties={"$current_url": "https://something.com"},
        )
        filter = Filter(
            data={
                "properties": [
                    {"key": "group", "operator": "lt", "value": 2, "type": "person"},
                    {"key": "group", "operator": "gt", "value": 0, "type": "person"},
                ]
            }
        )
        events = _filter_events(filter=filter, team=self.team, order_by=None)
        self.assertEqual(events[0]["id"], event2_uuid)
        self.assertEqual(len(events), 1)

    def test_boolean_filters(self):
        _create_event(team=self.team, event="$pageview", distinct_id="test")
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"is_first_user": True},
        )
        filter = Filter(data={"properties": [{"key": "is_first_user", "value": "true"}]})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event2_uuid)
        self.assertEqual(len(events), 1)

    def test_is_not_set_and_is_set(self):
        event1_uuid = _create_event(team=self.team, event="$pageview", distinct_id="test")
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"is_first_user": True},
        )
        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "is_first_user",
                        "operator": "is_not_set",
                        "value": "is_not_set",
                    }
                ]
            }
        )
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event1_uuid)
        self.assertEqual(len(events), 1)

        filter = Filter(data={"properties": [{"key": "is_first_user", "operator": "is_set", "value": "is_set"}]})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event2_uuid)
        self.assertEqual(len(events), 1)

    def test_is_not_set_and_is_set_with_missing_value(self):
        event1_uuid = _create_event(team=self.team, event="$pageview", distinct_id="test")
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"is_first_user": True},
        )
        filter = Filter(data={"properties": [{"key": "is_first_user", "operator": "is_not_set"}]})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event1_uuid)
        self.assertEqual(len(events), 1)

        filter = Filter(data={"properties": [{"key": "is_first_user", "operator": "is_set"}]})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event2_uuid)
        self.assertEqual(len(events), 1)

    def test_true_false(self):
        _create_event(team=self.team, distinct_id="test", event="$pageview")
        event2_uuid = _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"is_first": True},
        )
        filter = Filter(data={"properties": {"is_first": "true"}})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event2_uuid)

        filter = Filter(data={"properties": {"is_first": ["true"]}})
        events = _filter_events(filter, self.team)

        self.assertEqual(events[0]["id"], event2_uuid)

    def test_is_not_true_false(self):
        event_uuid = _create_event(team=self.team, distinct_id="test", event="$pageview")
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test",
            properties={"is_first": True},
        )
        filter = Filter(data={"properties": [{"key": "is_first", "value": "true", "operator": "is_not"}]})
        events = _filter_events(filter, self.team)
        self.assertEqual(events[0]["id"], event_uuid)

    def test_json_object(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"name": {"first_name": "Mary", "last_name": "Smith"}},
        )
        event1_uuid = _create_event(
            team=self.team,
            distinct_id="person1",
            event="$pageview",
            properties={"$current_url": "https://something.com"},
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
        events = _filter_events(filter=filter, team=self.team, order_by=None)
        self.assertEqual(events[0]["id"], event1_uuid)
        self.assertEqual(len(events), 1)

    def test_element_selectors(self):
        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id="distinct_id",
            elements=[
                Element.objects.create(tag_name="a"),
                Element.objects.create(tag_name="div"),
            ],
        )
        _create_event(team=self.team, event="$autocapture", distinct_id="distinct_id")
        filter = Filter(data={"properties": [{"key": "selector", "value": "div > a", "type": "element"}]})
        events = _filter_events(filter=filter, team=self.team)
        self.assertEqual(len(events), 1)

    def test_element_filter(self):
        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id="distinct_id",
            elements=[
                Element.objects.create(tag_name="a", text="some text"),
                Element.objects.create(tag_name="div"),
            ],
        )

        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id="distinct_id",
            elements=[
                Element.objects.create(tag_name="a", text="some other text"),
                Element.objects.create(tag_name="div"),
            ],
        )

        _create_event(team=self.team, event="$autocapture", distinct_id="distinct_id")
        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "text",
                        "value": ["some text", "some other text"],
                        "type": "element",
                    }
                ]
            }
        )
        events = _filter_events(filter=filter, team=self.team)
        self.assertEqual(len(events), 2)

        filter2 = Filter(data={"properties": [{"key": "text", "value": "some text", "type": "element"}]})
        events_response_2 = _filter_events(filter=filter2, team=self.team)
        self.assertEqual(len(events_response_2), 1)

    def test_filter_out_team_members(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["team_member"],
            properties={"email": "test@posthog.com"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["random_user"],
            properties={"email": "test@gmail.com"},
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
        _create_event(team=self.team, distinct_id="team_member", event="$pageview")
        _create_event(team=self.team, distinct_id="random_user", event="$pageview")
        filter = Filter(
            data={FILTER_TEST_ACCOUNTS: True, "events": [{"id": "$pageview"}]},
            team=self.team,
        )
        events = _filter_events(filter=filter, team=self.team)
        self.assertEqual(len(events), 1)

    def test_filter_out_team_members_with_grouped_properties(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"email": "test1@gmail.com", "name": "test", "age": "10"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "test2@gmail.com", "name": "test", "age": "20"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"email": "test3@gmail.com", "name": "test", "age": "30"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person4"],
            properties={"email": "test4@gmail.com", "name": "test", "age": "40"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person5"],
            properties={"email": "test@posthog.com", "name": "test", "age": "50"},
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

        journeys_for(
            team=self.team,
            create_people=False,
            events_by_person={
                "person1": [
                    {
                        "event": "$pageview",
                        "properties": {
                            "key": "val",
                            "$browser": "Safari",
                            "$browser_version": 14,
                        },
                    }
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "properties": {
                            "key": "val",
                            "$browser": "Safari",
                            "$browser_version": 14,
                        },
                    }
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "properties": {
                            "key": "val",
                            "$browser": "Safari",
                            "$browser_version": 14,
                        },
                    }
                ],
                "person4": [
                    {
                        "event": "$pageview",
                        "properties": {
                            "key": "val",
                            "$browser": "Safari",
                            "$browser_version": 14,
                        },
                    }
                ],
                "person5": [
                    {
                        "event": "$pageview",
                        "properties": {
                            "key": "val",
                            "$browser": "Safari",
                            "$browser_version": 14,
                        },
                    }
                ],
            },
        )

        filter = Filter(
            data={
                FILTER_TEST_ACCOUNTS: True,
                "events": [{"id": "$pageview"}],
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "age",
                                    "value": "10",
                                    "operator": "exact",
                                    "type": "person",
                                },
                                {
                                    "key": "age",
                                    "value": "20",
                                    "operator": "exact",
                                    "type": "person",
                                },
                                # choose person 1 and 2
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$browser",
                                    "value": "Safari",
                                    "operator": "exact",
                                    "type": "event",
                                },
                                {
                                    "key": "age",
                                    "value": "50",
                                    "operator": "exact",
                                    "type": "person",
                                },
                                # choose person 5
                            ],
                        },
                    ],
                },
            },
            team=self.team,
        )
        events = _filter_events(filter=filter, team=self.team)
        # test account filters delete person 5, so only 1 and 2 remain
        self.assertEqual(len(events), 2)

    def test_person_cohort_properties(self):
        person1_distinct_id = "person1"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"$some_prop": "something"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"type": "person", "key": "$some_prop", "value": "something"}]}],
            name="cohort1",
        )

        person2_distinct_id = "person2"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person2_distinct_id],
            properties={"$some_prop": "different"},
        )
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "type": "person",
                            "key": "$some_prop",
                            "value": "something",
                            "operator": "is_not",
                        }
                    ]
                }
            ],
            name="cohort2",
        )

        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]},
            team=self.team,
        )

        prop_clause, prop_clause_params = parse_prop_grouped_clauses(
            property_group=filter.property_groups,
            has_person_id_joined=False,
            team_id=self.team.pk,
            hogql_context=filter.hogql_context,
        )
        query = """
        SELECT distinct_id FROM person_distinct_id2 WHERE team_id = %(team_id)s {prop_clause}
        """.format(prop_clause=prop_clause)
        # get distinct_id column of result
        result = sync_execute(
            query,
            {
                "team_id": self.team.pk,
                **prop_clause_params,
                **filter.hogql_context.values,
            },
        )[0][0]
        self.assertEqual(result, person1_distinct_id)

        # test cohort2 with negation
        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}]},
            team=self.team,
        )
        prop_clause, prop_clause_params = parse_prop_grouped_clauses(
            property_group=filter.property_groups,
            has_person_id_joined=False,
            team_id=self.team.pk,
            hogql_context=filter.hogql_context,
        )
        query = """
        SELECT distinct_id FROM person_distinct_id2 WHERE team_id = %(team_id)s {prop_clause}
        """.format(prop_clause=prop_clause)
        # get distinct_id column of result
        result = sync_execute(
            query,
            {
                "team_id": self.team.pk,
                **prop_clause_params,
                **filter.hogql_context.values,
            },
        )[0][0]

        self.assertEqual(result, person2_distinct_id)

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
