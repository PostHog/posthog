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

        # Capture both events before polling to reduce wall-clock time
        first_timestamp = time.time()
        first_event_uuid = self.client.capture_event(
            event_name, distinct_id_1, {"$set": {"source": "first", "$test_timestamp": first_timestamp}}
        )
        second_timestamp = time.time()
        second_event_uuid = self.client.capture_event(
            event_name, distinct_id_2, {"$set": {"source": "second", "$test_timestamp": second_timestamp}}
        )

        # Poll for both events
        found_first = self.client.query_event_by_uuid(first_event_uuid)
        self.assert_event(found_first, first_event_uuid, event_name, distinct_id_1)
        found_second = self.client.query_event_by_uuid(second_event_uuid)
        self.assert_event(found_second, second_event_uuid, event_name, distinct_id_2)

        # Create alias: link distinct_id_2 to distinct_id_1
        alias_event_uuid = self.client.alias(distinct_id_2, distinct_id_1)

        # Wait for alias to propagate and query person by distinct_id_1
        person = self.client.query_person_by_distinct_id(distinct_id_1, min_timestamp=second_timestamp)
        assert person is not None, "Alias not propagated within time budget"

        # Query all events for this person - should have all 3 specific events
        events = self.client.query_events_by_person_id(person.id, expected_count=3)
        assert events is not None, "Expected at least 3 events for person after alias"

        event_uuids = {e.uuid for e in events}
        assert first_event_uuid in event_uuids, "First event not found in person's events"
        assert second_event_uuid in event_uuids, "Second event not found in person's events"
        assert alias_event_uuid in event_uuids, "Alias event not found in person's events"
