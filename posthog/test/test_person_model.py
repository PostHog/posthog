import datetime
import unittest
from unittest import mock

import pytz

from posthog.models import Action, ActionStep, Event, Person
from posthog.test.base import BaseTest


class TestPerson(BaseTest):
    @mock.patch("posthog.api.capture.capture_internal")
    def test_merge_people(self, mock_capture_internal):
        person0 = Person.objects.create(distinct_ids=["person_0"], team=self.team, properties={"$os": "Microsoft"})
        person0.created_at = datetime.datetime(2020, 1, 1, tzinfo=pytz.UTC)
        person0.save()

        person1 = Person.objects.create(distinct_ids=["person_1"], team=self.team, properties={"$os": "Chrome"})
        person1.created_at = datetime.datetime(2019, 7, 1, tzinfo=pytz.UTC)
        person1.save()

        Event.objects.create(event="user signed up", team=self.team, distinct_id="person_1")
        action = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action, event="user signed up")
        action.calculate_events()

        person2 = Person.objects.create(
            distinct_ids=["person_2"], team=self.team, properties={"$os": "Apple", "$browser": "MS Edge"},
        )
        person3 = Person.objects.create(distinct_ids=["person_3"], team=self.team, properties={"$os": "PlayStation"})

        self.assertEqual(len(Person.objects.all()), 4)

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
