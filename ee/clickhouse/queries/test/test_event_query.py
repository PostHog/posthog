from uuid import uuid4

import sqlparse

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
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
    is_static = kwargs.pop("is_static", False)
    cohort = Cohort.objects.create(team=team, name=name, groups=groups, is_static=is_static)
    return cohort


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

        query, params = TrendsEventQuery(filter=filter, entity=entity, team_id=self.team.pk).get_query()

        correct = """
        SELECT e.timestamp as timestamp,
        e.properties as properties
        FROM events e
        WHERE team_id = %(team_id)s
            AND event = %(event)s
            AND toStartOfDay(timestamp) >= toStartOfDay(toDateTime(%(date_from)s))
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

        global_prop_query, global_prop_query_params = TrendsEventQuery(
            filter=filter, entity=entity, team_id=self.team.pk
        ).get_query()
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

        entity_prop_query, entity_prop_query_params = TrendsEventQuery(
            filter=filter, entity=entity, team_id=self.team.pk
        ).get_query()

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

        global_prop_query, global_prop_query_params = TrendsEventQuery(
            filter=filter, entity=entity, team_id=self.team.pk
        ).get_query()
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

        entity_prop_query, entity_prop_query_params = TrendsEventQuery(
            filter=filter, entity=entity, team_id=self.team.pk
        ).get_query()

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

        query, params = TrendsEventQuery(filter=filter, entity=entity, team_id=self.team.pk).get_query()
        sync_execute(query, params)

    # just smoke test making sure query runs because no new functions are used here
    def test_entity_filtered_by_cohort(self):
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[{"properties": {"name": "test"}}])

        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [
                    {
                        "id": "$pageview",
                        "order": 0,
                        "properties": [{"key": "id", "type": "cohort", "value": cohort.pk}],
                    },
                ],
            }
        )

        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test"})
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-02T12:00:00Z")

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "foo"})
        _create_event(team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-02T12:01:00Z")

        query, params = TrendsEventQuery(filter=filter, entity=filter.entities[0], team_id=self.team.pk).get_query()
        sync_execute(query, params)

    # smoke test make sure query is formatted and runs
    def test_static_cohort_filter(self):
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[], is_static=True)

        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
                "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
            }
        )

        entity = Entity({"id": "viewed", "type": "events",})

        query, params = TrendsEventQuery(filter=filter, entity=entity, team_id=self.team.pk).get_query()
        sync_execute(query, params)

    def test_account_filters(self):
        person1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
        person2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

        _create_event(event="event_name", team=self.team, distinct_id="person_1")
        _create_event(event="event_name", team=self.team, distinct_id="person_2")
        _create_event(event="event_name", team=self.team, distinct_id="person_2")

        cohort = Cohort.objects.create(team=self.team, name="cohort1", groups=[{"properties": {"name": "Jane"}}])
        cohort.calculate_people()

        self.team.test_account_filters = [{"key": "id", "value": cohort.pk, "type": "cohort"}]
        self.team.save()

        filter = Filter(data={"events": [{"id": "event_name", "order": 0},], "filter_test_accounts": True})

        query, params = TrendsEventQuery(filter=filter, entity=filter.entities[0], team_id=self.team.pk).get_query()
        sync_execute(query, params)

    def test_denormalised_props(self):
        filters = {
            "events": [
                {
                    "id": "user signed up",
                    "type": "events",
                    "order": 0,
                    "properties": [{"key": "test_prop", "value": "hi"}],
                },
            ],
            "date_from": "2020-01-01",
            "properties": [{"key": "test_prop", "value": "hi"}],
            "date_to": "2020-01-14",
        }

        with self.settings(CLICKHOUSE_DENORMALIZED_PROPERTIES=["test_prop"]):

            p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"key": "value"})
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-02T12:00:00Z",
                properties={"test_prop": "hi"},
            )

            p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"key_2": "value_2"})
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="p2",
                timestamp="2020-01-02T12:00:00Z",
                properties={"test_prop": "hi"},
            )

            filter = Filter(data=filters)
            query, params = TrendsEventQuery(filter=filter, entity=filter.entities[0], team_id=self.team.pk).get_query()
            sync_execute(query, params)
            self.assertIn("properties_test_prop", query)
