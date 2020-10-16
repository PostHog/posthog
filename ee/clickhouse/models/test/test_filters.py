from typing import Optional
from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import ClickhouseEventSerializer, create_event
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.events import GET_EVENTS_WITH_PROPERTIES
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.cohort import Cohort
from posthog.models.event import Event
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.test.test_filter_model import property_to_Q_test_factory


def _filter_events(
    filter: Filter, team: Team, person_query: Optional[bool] = False, order_by: Optional[str] = None,
):
    prop_filters, prop_filter_params = parse_prop_clauses("uuid", filter.properties, team)
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


class TestClickhouseFiltering(
    ClickhouseTestMixin, property_to_Q_test_factory(_filter_events, _create_event, _create_person),  # type: ignore
):
    def test_person_cohort_properties(self):
        person1_distinct_id = "person1"
        person1 = Person.objects.create(
            team=self.team, distinct_ids=[person1_distinct_id], properties={"$some_prop": "something"}
        )
        cohort1 = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "something"}}], name="cohort1"
        )
        cohort1.people.add(person1)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})

        prop_clause, prop_clause_params = parse_prop_clauses("uuid", filter.properties, self.team)
        query = """
        SELECT * FROM person_distinct_id WHERE team_id = %(team_id)s {prop_clause}
        """.format(
            prop_clause=prop_clause
        )

        result = sync_execute(query, {"team_id": self.team.pk, **prop_clause_params})[0][
            2
        ]  # get person_id column of result
        self.assertTrue(result)
