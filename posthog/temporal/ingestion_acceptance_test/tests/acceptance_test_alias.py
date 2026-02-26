"""Alias test - verifies that alias links two distinct IDs to the same person."""

import time
import uuid

from ..runner import AcceptanceTest


class TestAlias(AcceptanceTest):
    """Test alias functionality."""

    def test_alias_merges_events_from_different_distinct_ids(self) -> None:
        """Send events with two distinct IDs, alias them, and verify both events belong to the same person."""
        event_name = "$test_alias"
        distinct_id_1 = str(uuid.uuid4())
        distinct_id_2 = str(uuid.uuid4())

        # First event with distinct_id_1
        first_timestamp = time.time()
        first_event_uuid = self.client.capture_event(
            event_name, distinct_id_1, {"$set": {"source": "first", "$test_timestamp": first_timestamp}}
        )
        found_first = self.client.query_event_by_uuid(first_event_uuid)
        self.assert_event(found_first, first_event_uuid, event_name, distinct_id_1)

        # Second event with distinct_id_2
        second_timestamp = time.time()
        second_event_uuid = self.client.capture_event(
            event_name, distinct_id_2, {"$set": {"source": "second", "$test_timestamp": second_timestamp}}
        )
        found_second = self.client.query_event_by_uuid(second_event_uuid)
        self.assert_event(found_second, second_event_uuid, event_name, distinct_id_2)

        # Create alias: link distinct_id_2 to distinct_id_1
        self.client.alias(distinct_id_2, distinct_id_1)

        # Wait for alias to propagate and query person by distinct_id_1
        person = self.client.query_person_by_distinct_id(distinct_id_1, min_timestamp=second_timestamp)
        assert person is not None, "Person not found after alias"

        # Query all events for this person - should have both events and the alias creation event
        events = self.client.query_events_by_person_id(person.id, expected_count=3)
        assert events is not None, "Expected 3 events for person after alias"
        assert len(events) == 3, f"Expected 3 events, got {len(events)}"

        # Verify both event UUIDs are present
        event_uuids = {e.uuid for e in events}
        assert first_event_uuid in event_uuids, "First event not found in person's events"
        assert second_event_uuid in event_uuids, "Second event not found in person's events"
