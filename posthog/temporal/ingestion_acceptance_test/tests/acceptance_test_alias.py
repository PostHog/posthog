"""Alias test - verifies that alias links two distinct IDs to the same person."""

import uuid

import structlog

from ..runner import AcceptanceTest

logger = structlog.get_logger(__name__)


class TestAlias(AcceptanceTest):
    """Test alias functionality."""

    def test_alias_merges_events_from_different_distinct_ids(self) -> None:
        """Send events with two distinct IDs, alias them, and verify both events belong to the same person."""
        event_name = "$test_alias"
        distinct_id_a = str(uuid.uuid4())  # Person A - will be aliased to
        distinct_id_b = str(uuid.uuid4())  # Person B - will be aliased from

        # Capture both events before polling to reduce wall-clock time
        logger.info("test_alias: capturing event for Person A", distinct_id=distinct_id_a)
        first_event_uuid = self.client.capture_event(
            event_name, distinct_id_a, {"$set": {"source": "first", "$test_version": 1}}
        )

        logger.info("test_alias: capturing event for Person B", distinct_id=distinct_id_b)
        second_event_uuid = self.client.capture_event(
            event_name, distinct_id_b, {"$set": {"source": "second", "$test_version": 2}}
        )

        # Poll for both events
        logger.info("test_alias: querying for Person A event", event_uuid=first_event_uuid)
        found_first = self.client.query_event_by_uuid(first_event_uuid)
        self.assert_event(found_first, first_event_uuid, event_name, distinct_id_a)

        logger.info("test_alias: querying for Person B event", event_uuid=second_event_uuid)
        found_second = self.client.query_event_by_uuid(second_event_uuid)
        self.assert_event(found_second, second_event_uuid, event_name, distinct_id_b)

        # Create alias: link Person B to Person A
        logger.info(
            "test_alias: creating alias from Person B to Person A", alias=distinct_id_b, distinct_id=distinct_id_a
        )
        alias_event_uuid = self.client.alias(distinct_id_b, distinct_id_a)

        # Wait for alias to propagate and query person by Person A's distinct_id
        logger.info("test_alias: querying for Person A after alias", distinct_id=distinct_id_a)
        person = self.client.query_person_by_distinct_id(distinct_id_a, min_version=2)
        assert person is not None, "Alias not propagated within time budget"

        # Query all events for this person - should have all 3 specific events
        logger.info("test_alias: querying events by person", person_id=person.id)
        expected_uuids = {first_event_uuid, second_event_uuid, alias_event_uuid}
        events = self.client.query_events_by_person_id(person.id, expected_event_uuids=expected_uuids)
        assert events is not None, "Expected events not found for person after alias within time budget"
