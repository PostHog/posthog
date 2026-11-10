from uuid import uuid4

from posthog.test.base import BaseTest

from posthog.models.event.util import create_event
from posthog.test.persons import create_person


def _create_event(**kwargs):
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)


class TestPerson(BaseTest):
    def test_person_is_identified(self):
        person_identified = create_person(team=self.team, is_identified=True)
        person_anonymous = create_person(team=self.team)
        self.assertEqual(person_identified.is_identified, True)
        self.assertEqual(person_anonymous.is_identified, False)
