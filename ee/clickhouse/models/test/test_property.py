from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.base import BaseTest
from posthog.models.cohort import Cohort
from posthog.models.event import Event
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.models.team import Team


def _create_event(**kwargs) -> Event:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return Event(pk=str(pk))


def _create_person(**kwargs) -> Person:
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


class TestPropFormat(ClickhouseTestMixin, BaseTest):
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

    def test_prop_person(self):

        _create_person(
            distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"email": "another@posthog.com"}
        )

        _create_person(distinct_ids=["some_id"], team_id=self.team.pk, properties={"email": "test@posthog.com"})

        _create_event(
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        filter = Filter(data={"properties": [{"key": "email", "value": "test@posthog.com", "type": "person"}],})
        query, params = parse_prop_clauses("uuid", filter.properties, self.team)

        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)

    def test_prop_event(self):

        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"attr": "some_other_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"attr": "some_val"},
        )

        filter = Filter(data={"properties": [{"key": "attr", "value": "some_val"}],})
        query, params = parse_prop_clauses("uuid", filter.properties, self.team)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)

        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)
