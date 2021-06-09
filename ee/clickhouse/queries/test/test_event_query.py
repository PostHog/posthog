from uuid import uuid4

import sqlparse

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from ee.clickhouse.util import ClickhouseTestMixin
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

        query, params = ClickhouseEventQuery(filter, entity, self.team.pk).get_query("event")

        correct = """
        SELECT event
        FROM events e
        WHERE team_id = %(team_id)s
            AND event = %(event)s
            AND timestamp >= '2021-05-01 00:00:00'
            AND timestamp <= '2021-05-07 23:59:59'
        """
        correct_params = {
            "team_id": self.team.pk,
            "event": "viewed",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 23:59:59",
        }

        self.assertEqual(sqlparse.format(query, reindent=True), sqlparse.format(correct, reindent=True))
        self.assertEqual(params, correct_params)

        sync_execute(query, params)

    def test_properties_filter(self):
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

        global_prop_query, global_prop_query_params = ClickhouseEventQuery(filter, entity, self.team.pk).get_query(
            "event"
        )
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

        entity_prop_query, entity_prop_query_params = ClickhouseEventQuery(filter, entity, self.team.pk).get_query(
            "event"
        )

        # global queries and enttiy queries should be the same
        self.assertEqual(
            sqlparse.format(global_prop_query, reindent=True), sqlparse.format(entity_prop_query, reindent=True)
        )
        sync_execute(entity_prop_query, entity_prop_query_params)

    def test_cohort_filter(self):
        pass

    def test_action_entity(self):
        pass
