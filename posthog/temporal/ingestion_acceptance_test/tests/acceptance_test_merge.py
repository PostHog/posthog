"""Merge test - verifies that $merge_dangerously merges two persons into one."""

import time
import uuid

from ..runner import AcceptanceTest


class TestMergeDangerously(AcceptanceTest):
    """Test $merge_dangerously functionality."""

    def test_merge_combines_two_persons_events(self) -> None:
        """Create two persons with events, merge them, and verify all events belong to the surviving person."""
        event_name = "$test_merge"
        distinct_id_a = str(uuid.uuid4())  # Person A - will survive the merge
        distinct_id_b = str(uuid.uuid4())  # Person B - will be merged into A

        # Create event for Person A
        timestamp_a = time.time()
        event_uuid_a = self.client.capture_event(
            event_name, distinct_id_a, {"$set": {"name": "Person A", "$test_timestamp": timestamp_a}}
        )
        found_a = self.client.query_event_by_uuid(event_uuid_a)
        self.assert_event(found_a, event_uuid_a, event_name, distinct_id_a)

        # Verify Person A exists
        person_a = self.client.query_person_by_distinct_id(distinct_id_a)
        assert person_a is not None, "Person A not found"

        # Create event for Person B
        timestamp_b = time.time()
        event_uuid_b = self.client.capture_event(
            event_name,
            distinct_id_b,
            {"$set": {"name": "Person B", "extra_prop": "from_b", "$test_timestamp": timestamp_b}},
        )
        found_b = self.client.query_event_by_uuid(event_uuid_b)
        self.assert_event(found_b, event_uuid_b, event_name, distinct_id_b)

        # Verify Person B exists
        person_b = self.client.query_person_by_distinct_id(distinct_id_b)
        assert person_b is not None, "Person B not found"

        # Merge Person B into Person A
        merge_event_uuid = self.client.merge_dangerously(distinct_id_a, distinct_id_b)
        found_merge = self.client.query_event_by_uuid(merge_event_uuid)
        assert found_merge is not None, "Merge event not found"

        # Wait for merge to propagate - Person A should have updated timestamp
        # We need to set a new timestamp on Person A to detect when merge completes
        post_merge_timestamp = time.time()
        post_merge_event_uuid = self.client.capture_event(
            "$test_post_merge", distinct_id_a, {"$set": {"$test_timestamp": post_merge_timestamp}}
        )
        found_post_merge = self.client.query_event_by_uuid(post_merge_event_uuid)
        assert found_post_merge is not None, "Post-merge event not found"

        # Query Person A with the post-merge timestamp to ensure merge has propagated
        merged_person = self.client.query_person_by_distinct_id(distinct_id_a, min_timestamp=post_merge_timestamp)
        assert merged_person is not None, "Merged person not found"

        # After merge, Person A should have Person B's extra_prop (properties merge)
        # Note: Person A's name takes precedence over Person B's name
        assert merged_person.properties.get("name") == "Person A", "Person A's name should take precedence"
        assert merged_person.properties.get("extra_prop") == "from_b", "Person B's extra_prop should be merged"

        # Query all events for the merged person - should have events from both A and B
        # Expected: event_a, event_b, merge_event, post_merge_event = 4 events
        events = self.client.query_events_by_person_id(merged_person.id, expected_count=4)
        assert events is not None, "Expected 4 events for merged person"

        # Verify both original event UUIDs are present
        event_uuids = {e.uuid for e in events}
        assert event_uuid_a in event_uuids, "Person A's event not found after merge"
        assert event_uuid_b in event_uuids, "Person B's event not found after merge"
