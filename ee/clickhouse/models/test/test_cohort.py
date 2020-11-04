from datetime import datetime
from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query, format_person_query
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person, create_person_distinct_id
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.base import BaseTest
from posthog.models.cohort import Cohort
from posthog.models.event import Event
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.models.utils import UUIDT


def _create_event(**kwargs) -> Event:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return Event(pk=str(pk))


# Some custom stuff for this test as going via Person postgres model won't allow 2 people with same ID
def _create_person(**kwargs) -> Person:
    if kwargs.get("uuid"):
        uuid = str(kwargs.pop("uuid"))
    else:
        uuid = str(UUIDT())
    distinct_ids = kwargs.pop("distinct_ids")
    person = create_person(uuid=uuid, **kwargs)
    for id in distinct_ids:
        create_person_distinct_id(0, kwargs["team_id"], id, str(person))
    return Person(id=person, uuid=person)


class TestCohort(ClickhouseTestMixin, BaseTest):
    def test_prop_cohort_basic(self):

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

        _create_person(
            distinct_ids=["some_id"],
            team_id=self.team.pk,
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        _create_event(
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": {"$some_prop": "something", "$another_prop": "something"}}],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})
        query, params = parse_prop_clauses("uuid", filter.properties, self.team)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)

    def test_prop_cohort_multiple_groups(self):

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

        _create_person(distinct_ids=["some_id"], team_id=self.team.pk, properties={"$another_prop": "something"})
        _create_event(
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": {"$some_prop": "something"}}, {"properties": {"$another_prop": "something"}}],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})
        query, params = parse_prop_clauses("uuid", filter.properties, self.team)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 2)

    def test_prop_cohort_with_negation(self):
        team2 = Team.objects.create()

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

        _create_person(distinct_ids=["some_id"], team_id=team2.pk, properties={"$another_prop": "something"})
        _create_event(
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop__is_not": "something"}}], name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})
        query, params = parse_prop_clauses("uuid", filter.properties, self.team)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 0)

    def test_cohort_updated_props(self):
        # The way clickhouse works is that updates aren't instant, so two people with the same ID are in the database
        # Make sure we get the last one.
        person1 = _create_person(
            distinct_ids=["some_other_id_2"],
            team_id=self.team.pk,
            properties={"$some_prop": "updated"},
            timestamp=datetime(2020, 1, 1, 12, 0, 1),
        )
        _create_person(
            uuid=person1.uuid,
            distinct_ids=["some_other_id"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
            timestamp=datetime(2020, 1, 1, 12, 0, 4),
        )

        cohort1 = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "updated"}}], name="cohort1",
        )

        final_query, params = format_filter_query(cohort1)

        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 0)
