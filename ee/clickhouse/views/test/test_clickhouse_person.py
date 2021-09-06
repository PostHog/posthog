import json
from uuid import uuid4

from rest_framework import status

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.util import format_ch_timestamp
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_person import factory_test_person
from posthog.models import Event, Person


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    return Event(pk=create_event(**kwargs))


def _get_events(team_id):
    return sync_execute("SELECT * FROM events WHERE team_id = %(team_id)s", {"team_id": team_id})


def _create_person(**kwargs):
    return Person.objects.create(**kwargs)


class ClickhouseTestPersonApi(
    ClickhouseTestMixin, factory_test_person(_create_event, _create_person, _get_events)  # type: ignore
):
    def test_filter_id_or_uuid(self) -> None:
        # Overriding this test due to only UUID being available on ClickHouse
        person1 = _create_person(team=self.team, properties={"$browser": "whatever", "$os": "Mac OS X"})
        person2 = _create_person(team=self.team, properties={"random_prop": "asdf"})
        _create_person(team=self.team, properties={"random_prop": "asdf"})

        response_uuid = self.client.get("/api/person/?uuid={},{}".format(person1.uuid, person2.uuid))
        self.assertEqual(response_uuid.status_code, 200)
        self.assertEqual(len(response_uuid.json()["results"]), 2)

        response_id = self.client.get("/api/person/?id={},{}".format(person1.id, person2.id))
        self.assertEqual(response_id.status_code, 422)
