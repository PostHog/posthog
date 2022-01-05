from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_person import factory_test_person
from posthog.models import Event, Person
from posthog.models.person import PersonDistinctId


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
    def test_split_person_clickhouse(self):
        person = _create_person(
            team=self.team, distinct_ids=["1", "2", "3"], properties={"$browser": "whatever", "$os": "Mac OS X"}
        )

        response = self.client.post("/api/person/%s/split/" % person.pk,).json()
        self.assertTrue(response["success"])

        people = Person.objects.all().order_by("id")
        clickhouse_people = sync_execute(
            "SELECT id FROM person FINAL WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        self.assertCountEqual(clickhouse_people, [(person.uuid,) for person in people])

        distinct_id_rows = PersonDistinctId.objects.all().order_by("person_id")
        pdis = sync_execute(
            "SELECT person_id, distinct_id FROM person_distinct_id FINAL WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )
        self.assertCountEqual(pdis, [(pdi.person.uuid, pdi.distinct_id) for pdi in distinct_id_rows])

        pdis2 = sync_execute(
            "SELECT person_id, distinct_id FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )
        self.assertCountEqual(pdis2, [(pdi.person.uuid, pdi.distinct_id) for pdi in distinct_id_rows])
