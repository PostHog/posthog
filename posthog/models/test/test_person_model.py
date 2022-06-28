import datetime
import unittest
from unittest import mock
from uuid import uuid4

import pytz

from posthog.client import sync_execute
from posthog.models import Action, ActionStep, Person
from posthog.models.event.util import create_event
from posthog.models.person.util import delete_person
from posthog.test.base import BaseTest


def _create_event(**kwargs):
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)


class TestPerson(BaseTest):
    @mock.patch("posthog.api.capture.capture_internal")
    def test_merge_people(self, mock_capture_internal):
        person0 = Person.objects.create(distinct_ids=["person_0"], team=self.team, properties={"$os": "Microsoft"})
        person0.created_at = datetime.datetime(2020, 1, 1, tzinfo=pytz.UTC)
        person0.save()

        person1 = Person.objects.create(distinct_ids=["person_1"], team=self.team, properties={"$os": "Chrome"})
        person1.created_at = datetime.datetime(2019, 7, 1, tzinfo=pytz.UTC)
        person1.save()

        action = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action, event="user signed up")

        person2 = Person.objects.create(
            distinct_ids=["person_2"], team=self.team, properties={"$os": "Apple", "$browser": "MS Edge"},
        )
        person3 = Person.objects.create(distinct_ids=["person_3"], team=self.team, properties={"$os": "PlayStation"})

        self.assertEqual(Person.objects.count(), 4)

        person0.merge_people([person1, person2, person3])

        mock_capture_internal.assert_has_calls(
            [
                mock.call(
                    {"event": "$create_alias", "properties": {"alias": "person_1"}},
                    "person_0",
                    None,
                    None,
                    unittest.mock.ANY,
                    unittest.mock.ANY,
                    self.team.id,
                ),
                mock.call(
                    {"event": "$create_alias", "properties": {"alias": "person_2"}},
                    "person_0",
                    None,
                    None,
                    unittest.mock.ANY,
                    unittest.mock.ANY,
                    self.team.id,
                ),
                mock.call(
                    {"event": "$create_alias", "properties": {"alias": "person_3"}},
                    "person_0",
                    None,
                    None,
                    unittest.mock.ANY,
                    unittest.mock.ANY,
                    self.team.id,
                ),
            ]
        )

    def test_person_is_identified(self):
        person_identified = Person.objects.create(team=self.team, is_identified=True)
        person_anonymous = Person.objects.create(team=self.team)
        self.assertEqual(person_identified.is_identified, True)
        self.assertEqual(person_anonymous.is_identified, False)

    def test_delete_person(self):
        person = Person.objects.create(team=self.team)
        delete_person(person)
        ch_persons = sync_execute(
            "SELECT version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual(ch_persons, [(100, 1, "{}")])

    def test_delete_person_and_ids(self):
        person = Person.objects.create(team=self.team, distinct_ids=["distinct_id1"])

        def get_ch_distinct_ids():
            return sync_execute(
                "SELECT version, is_deleted FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s and distinct_id = %(distinct_id)s",
                {"team_id": self.team.pk, "distinct_id": "distinct_id1"},
            )

        ch_distinct_ids = get_ch_distinct_ids()
        self.assertEqual(ch_distinct_ids, [(0, 0)])

        delete_person(person, delete_distinct_ids=True)
        ch_distinct_ids = get_ch_distinct_ids()
        self.assertEqual(ch_distinct_ids, [(0, 1)])

    def test_delete_person_and_events(self):
        person = Person.objects.create(team=self.team, distinct_ids=["distinct_id1"])

        _create_event(team=self.team, distinct_id="distinct_id1", event="$pageview")

        def count_events():
            return sync_execute("SELECT count(*) FROM events FINAL",)

        event_count = count_events()
        self.assertEqual(event_count[0][0], 1)

        delete_person(person, delete_events=True)
        event_count = count_events()
        self.assertEqual(event_count[0][0], 0)
