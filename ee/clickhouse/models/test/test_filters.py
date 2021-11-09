from typing import Optional
from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import ClickhouseEventSerializer, create_event
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.events import GET_EVENTS_WITH_PROPERTIES
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.cohort import Cohort
from posthog.models.event import Event
from posthog.models.filters import Filter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.test.test_filter import TestFilter as PGTestFilters
from posthog.models.filters.test.test_filter import property_to_Q_test_factory
from posthog.models.person import Person
from posthog.models.team import Team


def _filter_events(
    filter: Filter, team: Team, person_query: Optional[bool] = False, order_by: Optional[str] = None,
):
    prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)
    params = {"team_id": team.pk, **prop_filter_params}

    if order_by == "id":
        order_by = "uuid"

    events = sync_execute(
        GET_EVENTS_WITH_PROPERTIES.format(
            filters=prop_filters, order_by="ORDER BY {}".format(order_by) if order_by else "",
        ),
        params,
    )
    parsed_events = ClickhouseEventSerializer(events, many=True, context={"elements": None, "people": None}).data
    return parsed_events


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


def _create_event(**kwargs):
    uuid = uuid4()
    kwargs.update({"event_uuid": uuid})
    create_event(**kwargs)
    return Event(id=str(uuid))


class TestFilters(PGTestFilters):
    def test_simplify_cohorts(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}]}],
        )
        cohort.calculate_people_ch()

        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"},]},
        )

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            self.assertEqual(
                filter.simplify(self.team).properties_to_dict(),
                {"properties": [{"type": "precalculated-cohort", "key": "id", "value": cohort.pk, "operator": None},]},
            )

    def test_simplify_not_ee(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}]}],
        )
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team, is_clickhouse_enabled=False).properties_to_dict(),
            {"properties": [{"type": "cohort", "key": "id", "value": cohort.pk, "operator": None}]},
        )

    def test_simplify_static_cohort(self):
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {"properties": [{"type": "static-cohort", "key": "id", "value": cohort.pk, "operator": None},]},
        )

    def test_simplify_hasdone_cohort(self):
        cohort = Cohort.objects.create(team=self.team, groups=[{"event_id": "$pageview", "days": 1}])
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {"properties": [{"type": "cohort", "key": "id", "value": cohort.pk, "operator": None}]},
        )

    def test_simplify_multi_group_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": {"$some_prop": "something"}}, {"properties": {"$another_prop": "something"}}],
        )
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {"properties": [{"type": "cohort", "key": "id", "value": cohort.pk, "operator": None}]},
        )

    def test_recursive_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}]}],
        )
        recursive_cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"type": "cohort", "key": "id", "value": cohort.pk, "operator": None}]}],
        )
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": recursive_cohort.pk}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"},]},
        )

    def test_simplify_no_such_cohort(self):
        filter = Filter(data={"properties": [{"type": "cohort", "key": "id", "value": 555_555}]})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {"properties": [{"type": "cohort", "key": "id", "value": 555_555, "operator": None}]},
        )

    def test_simplify_entities(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}]}],
        )
        filter = Filter(
            data={"events": [{"id": "$pageview", "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}]}]}
        )

        self.assertEqual(
            filter.simplify(self.team).entities_to_dict(),
            {
                "events": [
                    {
                        "type": "events",
                        "id": "$pageview",
                        "math": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "custom_name": None,
                        "order": None,
                        "name": "$pageview",
                        "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"},],
                    }
                ],
            },
        )

    def test_simplify_entities_with_group_math(self):
        filter = Filter(data={"events": [{"id": "$pageview", "math": "unique_group", "math_group_type_index": 2}]})

        self.assertEqual(
            filter.simplify(self.team).entities_to_dict(),
            {
                "events": [
                    {
                        "type": "events",
                        "id": "$pageview",
                        "math": "unique_group",
                        "math_property": None,
                        "math_group_type_index": 2,
                        "custom_name": None,
                        "order": None,
                        "name": "$pageview",
                        "properties": [{"key": "$group_2", "operator": "is_not", "value": "", "type": "event"},],
                    }
                ],
            },
        )

    def test_simplify_when_aggregating_by_group(self):
        filter = RetentionFilter(data={"aggregation_group_type_index": 0})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {"properties": [{"key": "$group_0", "operator": "is_not", "value": "", "type": "event"}]},
        )

    def test_simplify_funnel_entities_when_aggregating_by_group(self):
        filter = Filter(data={"events": [{"id": "$pageview"}], "aggregation_group_type_index": 2})

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {"properties": [{"key": "$group_2", "operator": "is_not", "value": "", "type": "event"}]},
        )


class TestFiltering(
    ClickhouseTestMixin, property_to_Q_test_factory(_filter_events, _create_event, _create_person),  # type: ignore
):
    def test_person_cohort_properties(self):
        person1_distinct_id = "person1"
        person1 = Person.objects.create(
            team=self.team, distinct_ids=[person1_distinct_id], properties={"$some_prop": "something"}
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"type": "person", "key": "$some_prop", "value": "something"}]}],
            name="cohort1",
        )

        person2_distinct_id = "person2"
        person2 = Person.objects.create(
            team=self.team, distinct_ids=[person2_distinct_id], properties={"$some_prop": "different"}
        )
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {"properties": [{"type": "person", "key": "$some_prop", "value": "something", "operator": "is_not"}]}
            ],
            name="cohort2",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],}, team=self.team)

        prop_clause, prop_clause_params = parse_prop_clauses(
            filter.properties, self.team.pk, has_person_id_joined=False
        )
        query = """
        SELECT distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s {prop_clause}
        """.format(
            prop_clause=prop_clause
        )
        # get distinct_id column of result
        result = sync_execute(query, {"team_id": self.team.pk, **prop_clause_params})[0][0]
        self.assertEqual(result, person1_distinct_id)

        # test cohort2 with negation
        filter = Filter(data={"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}],}, team=self.team)
        prop_clause, prop_clause_params = parse_prop_clauses(
            filter.properties, self.team.pk, has_person_id_joined=False
        )
        query = """
        SELECT distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s {prop_clause}
        """.format(
            prop_clause=prop_clause
        )
        # get distinct_id column of result
        result = sync_execute(query, {"team_id": self.team.pk, **prop_clause_params})[0][0]

        self.assertEqual(result, person2_distinct_id)
