from typing import Dict, List
from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.cohort import Cohort
from posthog.models.event import Event
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.test.base import BaseTest


def _create_event(**kwargs) -> Event:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return Event(pk=str(pk))


def _create_person(**kwargs) -> Person:
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


class TestPropFormat(ClickhouseTestMixin, BaseTest):
    def test_prop_person(self):

        _create_person(
            distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"email": "another@posthog.com"}
        )

        _create_person(distinct_ids=["some_id"], team_id=self.team.pk, properties={"email": "test@posthog.com"})

        _create_event(
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        filter = Filter(data={"properties": [{"key": "email", "value": "test@posthog.com", "type": "person"}],})
        query, params = parse_prop_clauses(filter.properties, self.team.pk)

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
        query, params = parse_prop_clauses(filter.properties, self.team.pk)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)

        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)

    def _run_query(self, filter: Filter) -> List:
        query, params = parse_prop_clauses(filter.properties, self.team.pk, allow_denormalized_props=True)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        # Make sure we don't accidentally use json on the properties field
        self.assertNotIn("json", final_query.lower())
        return sync_execute(final_query, {**params, "team_id": self.team.pk})

    def test_prop_event_denormalized(self):
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": "some_other_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": "some_val"},
        )

        with self.settings(CLICKHOUSE_DENORMALIZED_PROPERTIES=["test_prop", "something_else"]):
            filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val"}],})
            self.assertEqual(len(self._run_query(filter)), 1)

            filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val", "operator": "is_not"}],})
            self.assertEqual(len(self._run_query(filter)), 1)

            filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val", "operator": "is_set"}],})
            self.assertEqual(len(self._run_query(filter)), 2)

            filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val", "operator": "is_not_set"}],})
            self.assertEqual(len(self._run_query(filter)), 0)

            filter = Filter(data={"properties": [{"key": "test_prop", "value": "_other_", "operator": "icontains"}],})
            self.assertEqual(len(self._run_query(filter)), 1)

            filter = Filter(
                data={"properties": [{"key": "test_prop", "value": "_other_", "operator": "not_icontains"}],}
            )
            self.assertEqual(len(self._run_query(filter)), 1)

    def test_prop_event_denormalized_ints(self):
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 0},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 2},
        )

        with self.settings(CLICKHOUSE_DENORMALIZED_PROPERTIES=["test_prop", "something_else"]):
            filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "gt"}],})
            self.assertEqual(len(self._run_query(filter)), 1)

            filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "lt"}],})
            self.assertEqual(len(self._run_query(filter)), 1)

            filter = Filter(data={"properties": [{"key": "test_prop", "value": 0}],})
            self.assertEqual(len(self._run_query(filter)), 1)
