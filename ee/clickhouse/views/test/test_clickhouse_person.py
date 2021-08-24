from uuid import uuid4

from rest_framework import status

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_person import factory_test_person
from posthog.models import Event, Person


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    return Event(pk=create_event(**kwargs))


def _get_events(team_id):
    return sync_execute("select * from events FINAL where team_id = %(team_id)s", {"team_id": team_id})


def _create_person(**kwargs):
    return Person.objects.create(**kwargs)


class ClickhouseTestPersonApi(
    ClickhouseTestMixin, factory_test_person(_create_event, _create_person, _get_events)  # type: ignore
):
    def test_delete_person(self):
        person = _create_person(
            team=self.team, distinct_ids=["person_1", "anonymous_id"], properties={"$os": "Chrome"},
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        _create_event(event="test", team=self.team, distinct_id="anonymous_id")
        _create_event(event="test", team=self.team, distinct_id="someone_else")

        response = self.client.delete(f"/api/person/{person.pk}/")
        print(sync_execute("show create events"))
        print(sync_execute(f"SELECT * FROM events where team_id = {self.team.pk}"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content, b"")  # Empty response
        self.assertEqual(len(Person.objects.filter(team=self.team)), 0)
        self.assertEqual(len(_get_events(team_id=self.team.pk)), 1)

        response = self.client.delete(f"/api/person/{person.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
