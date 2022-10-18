from uuid import uuid4

from posthog.client import sync_execute
from posthog.models import Person
from posthog.models.event.util import create_event
from posthog.models.person.util import delete_ch_distinct_ids, delete_person
from posthog.test.base import BaseTest


def _create_event(**kwargs):
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)


class TestPerson(BaseTest):
    def test_person_is_identified(self):
        person_identified = Person.objects.create(team=self.team, is_identified=True)
        person_anonymous = Person.objects.create(team=self.team)
        self.assertEqual(person_identified.is_identified, True)
        self.assertEqual(person_anonymous.is_identified, False)

    def test_delete_person(self):
        person = Person.objects.create(team=self.team)
        delete_person(person)
        ch_persons = sync_execute(
            "SELECT toString(id), version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual(ch_persons, [(str(person.uuid), 100, 1, "{}")])

    def test_delete_ch_distinct_ids(self):
        person = Person.objects.create(team=self.team, distinct_ids=["distinct_id1"])

        ch_distinct_ids = sync_execute(
            "SELECT version, is_deleted FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s and distinct_id = %(distinct_id)s",
            {"team_id": self.team.pk, "distinct_id": "distinct_id1"},
        )
        self.assertEqual(ch_distinct_ids, [(0, 0)])

        delete_ch_distinct_ids(person)
        ch_distinct_ids = sync_execute(
            "SELECT toString(person_id), version, is_deleted FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s and distinct_id = %(distinct_id)s",
            {"team_id": self.team.pk, "distinct_id": "distinct_id1"},
        )
        self.assertEqual(ch_distinct_ids, [(str(person.uuid), 0, 1)])
