from uuid import uuid4

from posthog.test.base import BaseTest

from posthog.clickhouse.client import sync_execute
from posthog.models import Person, PersonDistinctId
from posthog.models.event.util import create_event
from posthog.models.person.util import delete_person


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
        person = Person.objects.create(
            team=self.team, version=15
        )  # version be > 0 to check that we don't just assume 0 in deletes
        delete_person(person, sync=True)
        ch_persons = sync_execute(
            "SELECT toString(id), version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual(ch_persons, [(str(person.uuid), 115, 1, "{}")])

    def test_delete_ch_distinct_ids(self):
        person = Person.objects.create(team=self.team)
        PersonDistinctId.objects.create(team=self.team, person=person, distinct_id="distinct_id1", version=15)

        ch_distinct_ids = sync_execute(
            "SELECT is_deleted FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s and distinct_id = %(distinct_id)s",
            {"team_id": self.team.pk, "distinct_id": "distinct_id1"},
        )
        self.assertEqual(ch_distinct_ids, [(0,)])

        delete_person(person, sync=True)
        ch_distinct_ids = sync_execute(
            "SELECT toString(person_id), version, is_deleted FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s and distinct_id = %(distinct_id)s",
            {"team_id": self.team.pk, "distinct_id": "distinct_id1"},
        )
        self.assertEqual(ch_distinct_ids, [(str(person.uuid), 115, 1)])
