import uuid

from django.utils import timezone

from ee.dynamodb.events import update_event_person
from ee.dynamodb.models.events import Event
from ee.dynamodb.util import DynamodbTestMixin
from posthog.api.test.base import BaseTest


class DynamodbStoreEvent(DynamodbTestMixin, BaseTest):
    def _generate_event(self, distinct_id=None, person_uuid=None):
        event_uuid = str(uuid.uuid4())
        if not person_uuid:
            person_uuid = str(uuid.uuid4())
        if not distinct_id:
            distinct_id = str(uuid.uuid4())

        event = Event(
            distinct_id=distinct_id,
            uuid=event_uuid,
            event="$pageview",
            properties={"wow": "such event"},
            timestamp=timezone.now(),
            team_id=2,
            created_at=timezone.now(),
            elements_chain="wow.such chain",
            person_uuid=person_uuid,
        )
        event.save()
        return distinct_id, event_uuid, event

    def test_save_event(self) -> None:
        distinct_id, event_uuid, event = self._generate_event()
        received_event = Event.get(distinct_id, event_uuid)
        self.assertEqual(event.uuid, received_event.uuid)
        self.assertEqual(event.distinct_id, received_event.distinct_id)
        self.assertEqual(event.event, received_event.event)
        self.assertEqual(event.properties, received_event.properties)
        self.assertEqual(event.timestamp, received_event.timestamp)
        self.assertEqual(event.team_id, received_event.team_id)
        self.assertEqual(event.created_at, received_event.created_at)
        self.assertEqual(event.elements_chain, received_event.elements_chain)
        self.assertEqual(event.person_uuid, received_event.person_uuid)

    def test_query_events(self):
        distinct_id = str(uuid.uuid4())
        # test getting multiple events with same distinct_id

        events = []
        for i in range(0, 4):
            events.append(self._generate_event(distinct_id=distinct_id))

        event_uuids = set([e[1] for e in events])
        queried_events = Event.query(distinct_id)
        queried_event_uuids = set([e.uuid for e in queried_events])

        self.assertEqual(event_uuids, queried_event_uuids)

    def test_update_events_person(self):
        """
        test_update_events_person tests to see if things will work when we update person_id on events in dynamo
        """
        distinct_id = str(uuid.uuid4())
        original_person_uuid = str(uuid.uuid4())

        events = []
        for i in range(0, 4):
            events.append(self._generate_event(distinct_id=distinct_id, person_uuid=original_person_uuid))

        event_person_uuids = set([e[2].person_uuid for e in events])

        self.assertEqual(event_person_uuids, {original_person_uuid})

        updated_person_uuid = str(uuid.uuid4())
        update_event_person(distinct_id, updated_person_uuid)

        queried_events = Event.query(distinct_id)
        updated_event_person_uuids = set([e.person_uuid for e in queried_events])

        self.assertNotEqual(event_person_uuids, updated_event_person_uuids)
        self.assertEqual(updated_event_person_uuids, {updated_person_uuid})
