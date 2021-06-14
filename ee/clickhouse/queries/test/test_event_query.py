from uuid import uuid4

import sqlparse

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups)
    return cohort


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


class TestEventQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        self._create_sample_data()
        super().setUp()

    def _create_sample_data(self):
        _create_person(distinct_ids=["user_one"], team=self.team)

        _create_event(event="viewed", distinct_id="user_one", team=self.team, timestamp="2021-05-01 00:00:00")

    def test_basic_event_filter(self):
        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
            }
        )

        entity = Entity({"id": "viewed", "type": "events"})

        query, params = ClickhouseEventQuery(filter, entity, self.team.pk).get_query()

        correct = """
        SELECT e.timestamp as timestamp,
        e.properties as properties
        FROM events e
        WHERE team_id = %(team_id)s
            AND event = %(event)s
            AND timestamp >= '2021-05-01 00:00:00'
            AND timestamp <= '2021-05-07 23:59:59'
        """

        self.assertEqual(sqlparse.format(query, reindent=True), sqlparse.format(correct, reindent=True))

        sync_execute(query, params)

    def test_person_properties_filter(self):
        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
                "properties": [
                    {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
                    {"key": "key", "value": "val"},
                ],
            }
        )

        entity = Entity({"id": "viewed", "type": "events"})

        global_prop_query, global_prop_query_params = ClickhouseEventQuery(filter, entity, self.team.pk).get_query()
        sync_execute(global_prop_query, global_prop_query_params)

        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
            }
        )

        entity = Entity(
            {
                "id": "viewed",
                "type": "events",
                "properties": [
                    {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
                    {"key": "key", "value": "val"},
                ],
            }
        )

        entity_prop_query, entity_prop_query_params = ClickhouseEventQuery(filter, entity, self.team.pk).get_query()

        # global queries and enttiy queries should be the same
        self.assertEqual(
            sqlparse.format(global_prop_query, reindent=True), sqlparse.format(entity_prop_query, reindent=True)
        )
        sync_execute(entity_prop_query, entity_prop_query_params)

    def test_event_properties_filter(self):
        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
                "properties": [{"key": "some_key", "value": "test_val", "operator": "exact", "type": "event"}],
            }
        )

        entity = Entity({"id": "viewed", "type": "events"})

        global_prop_query, global_prop_query_params = ClickhouseEventQuery(filter, entity, self.team.pk).get_query()
        sync_execute(global_prop_query, global_prop_query_params)

        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
            }
        )

        entity = Entity(
            {
                "id": "viewed",
                "type": "events",
                "properties": [{"key": "some_key", "value": "test_val", "operator": "exact", "type": "event"}],
            }
        )

        entity_prop_query, entity_prop_query_params = ClickhouseEventQuery(filter, entity, self.team.pk).get_query()

        # global queries and enttiy queries should be the same
        self.assertEqual(
            sqlparse.format(global_prop_query, reindent=True), sqlparse.format(entity_prop_query, reindent=True)
        )

        sync_execute(entity_prop_query, entity_prop_query_params)

    # just smoke test making sure query runs because no new functions are used here
    def test_cohort_filter(self):
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[{"properties": {"name": "test"}}])

        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
                "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
            }
        )

        entity = Entity({"id": "viewed", "type": "events",})

        query, params = ClickhouseEventQuery(filter, entity, self.team.pk).get_query()
        sync_execute(query, params)
        print(sqlparse.format(query, reindent=True))
