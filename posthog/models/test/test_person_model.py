import datetime as dt
from uuid import uuid4

from freezegun.api import freeze_time

from posthog.client import sync_execute
from posthog.models import Person, PersonDistinctId, PersonOverride
from posthog.models.event.util import create_event
from posthog.models.person.util import delete_person
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


class TestPersonOverride(BaseTest):
    @freeze_time("2021-01-21 00:00:00")
    def test_person_override_is_short_term(self):
        """Assert PersonOverride created less than 45 days ago is not long term."""
        old_person_created_at = dt.datetime.utcnow() - dt.timedelta(days=44, hours=23, minutes=59, seconds=59)
        old_person_id = uuid4()
        override_person_id = uuid4()

        person_override = PersonOverride.objects.create_override(
            team=self.team,
            old_person_id=old_person_id,
            override_person_id=override_person_id,
            old_person_created_at=old_person_created_at,
        )

        self.assertFalse(person_override.is_long_term)
        self.assertEqual(person_override.old_person_created_at, old_person_created_at)

    @freeze_time("2021-01-21 00:00:00")
    def test_person_override_is_long_term(self):
        """Assert PersonOverride created more than 45 days ago is long term."""
        old_person_created_at = dt.datetime.utcnow() - dt.timedelta(days=45, seconds=1)
        old_person_id = uuid4()
        override_person_id = uuid4()

        person_override = PersonOverride.objects.create_override(
            team=self.team,
            old_person_id=old_person_id,
            override_person_id=override_person_id,
            old_person_created_at=old_person_created_at,
        )

        self.assertTrue(person_override.is_long_term)
        self.assertEqual(person_override.old_person_created_at, old_person_created_at)
