"""Event properties capture test - verifies $set, $set_once, and $unset person properties."""

import uuid

import structlog

from ..runner import AcceptanceTest

logger = structlog.get_logger(__name__)


class TestPersonPropertiesCapture(AcceptanceTest):
    """Test event capture with person properties."""

    def test_set_person_properties(self) -> None:
        """Capture an event with $set person properties and verify they appear on person."""
        event_name = "$set_person_properties"
        distinct_id = str(uuid.uuid4())
        expected_person_props = {"email": "test@example.com", "name": "Test User"}

        logger.info("test_set_person_properties: capturing event", distinct_id=distinct_id)
        event_uuid = self.client.capture_event(event_name, distinct_id, {"$set": expected_person_props})

        logger.info("test_set_person_properties: querying for event", event_uuid=event_uuid)
        found_event = self.client.query_event_by_uuid(event_uuid)
        found_event = self.assert_event(found_event, event_uuid, event_name, distinct_id)

        set_props = found_event.properties.get("$set")
        assert set_props is not None, "$set properties not found in event"
        self.assert_properties_contain(set_props, expected_person_props, "event $set")

        logger.info("test_set_person_properties: querying for person", distinct_id=distinct_id)
        person = self.client.query_person_by_distinct_id(distinct_id)
        assert person is not None, "Person not found within time budget"
        self.assert_properties_contain(person.properties, expected_person_props, "person")

    def test_set_once_person_properties(self) -> None:
        """Verify $set_once only sets properties if they don't already exist."""
        event_name = "$set_once_person_properties"
        distinct_id = str(uuid.uuid4())
        initial_props = {"initial_referrer": "google"}

        # First event: set initial values with $set_once
        logger.info("test_set_once: capturing first event", distinct_id=distinct_id)
        first_event_uuid = self.client.capture_event(
            event_name, distinct_id, {"$set_once": initial_props, "$set": {"$test_version": 1}}
        )

        logger.info("test_set_once: querying for first event", event_uuid=first_event_uuid)
        found_first = self.client.query_event_by_uuid(first_event_uuid)
        self.assert_event(found_first, first_event_uuid, event_name, distinct_id)

        logger.info("test_set_once: querying for person after first event", distinct_id=distinct_id)
        person = self.client.query_person_by_distinct_id(distinct_id)
        assert person is not None, "Person not found within time budget"
        self.assert_properties_contain(person.properties, initial_props, "person after first event")

        # Second event: try to overwrite with $set_once (should not change existing)
        logger.info("test_set_once: capturing second event", distinct_id=distinct_id)
        second_props = {
            "$set_once": {
                "initial_referrer": "facebook",  # should NOT overwrite
                "new_property": "should_be_set",  # should be set
            },
            "$set": {"$test_version": 2},
        }
        second_event_uuid = self.client.capture_event(event_name, distinct_id, second_props)

        logger.info("test_set_once: querying for second event", event_uuid=second_event_uuid)
        found_second = self.client.query_event_by_uuid(second_event_uuid)
        self.assert_event(found_second, second_event_uuid, event_name, distinct_id)

        logger.info("test_set_once: querying for person after second event", distinct_id=distinct_id)
        person_after = self.client.query_person_by_distinct_id(distinct_id, min_version=2)
        assert person_after is not None, "Person updates not found within time budget"
        # Original values preserved, new property added
        expected_props = {"initial_referrer": "google", "new_property": "should_be_set"}
        self.assert_properties_contain(person_after.properties, expected_props, "person after second event")

    def test_unset_person_properties(self) -> None:
        """Verify $unset removes properties from person profile."""
        event_name = "$unset_person_properties"
        distinct_id = str(uuid.uuid4())
        initial_props = {
            "email": "test@example.com",
            "name": "Test User",
            "temporary_flag": "to_be_removed",
        }

        # First event: set initial properties
        logger.info("test_unset: capturing first event", distinct_id=distinct_id)
        first_event_uuid = self.client.capture_event(
            event_name, distinct_id, {"$set": {**initial_props, "$test_version": 1}}
        )

        logger.info("test_unset: querying for first event", event_uuid=first_event_uuid)
        found_first = self.client.query_event_by_uuid(first_event_uuid)
        self.assert_event(found_first, first_event_uuid, event_name, distinct_id)

        logger.info("test_unset: querying for person after first event", distinct_id=distinct_id)
        person = self.client.query_person_by_distinct_id(distinct_id)
        assert person is not None, "Person not found after first event"
        self.assert_properties_contain(person.properties, initial_props, "person after first event")

        # Second event: unset specific properties
        logger.info("test_unset: capturing second event with $unset", distinct_id=distinct_id)
        second_event_uuid = self.client.capture_event(
            event_name, distinct_id, {"$unset": ["temporary_flag"], "$set": {"$test_version": 2}}
        )

        logger.info("test_unset: querying for second event", event_uuid=second_event_uuid)
        found_second = self.client.query_event_by_uuid(second_event_uuid)
        self.assert_event(found_second, second_event_uuid, event_name, distinct_id)

        # Verify properties are removed, others remain
        logger.info("test_unset: querying for person after $unset", distinct_id=distinct_id)
        person_after = self.client.query_person_by_distinct_id(distinct_id, min_version=2)
        assert person_after is not None, "$unset event not propagated within time budget"
        assert person_after.properties.get("temporary_flag") is None, "$unset should remove the property"
        expected_remaining = {"email": "test@example.com", "name": "Test User"}
        self.assert_properties_contain(person_after.properties, expected_remaining, "remaining properties")

    def test_combined_set_set_once_unset(self) -> None:
        """Verify $set, $set_once, and $unset work together in same event."""
        event_name = "$set_set_once_unset_person_properties"
        distinct_id = str(uuid.uuid4())

        # First event: set initial properties
        logger.info("test_combined: capturing first event", distinct_id=distinct_id)
        first_props = {
            "$set": {"plan": "free", "to_remove": "temporary", "$test_version": 1},
            "$set_once": {"first_plan": "free"},
        }
        first_event_uuid = self.client.capture_event(event_name, distinct_id, first_props)

        logger.info("test_combined: querying for first event", event_uuid=first_event_uuid)
        found_first = self.client.query_event_by_uuid(first_event_uuid)
        self.assert_event(found_first, first_event_uuid, event_name, distinct_id)

        logger.info("test_combined: querying for person after first event", distinct_id=distinct_id)
        person = self.client.query_person_by_distinct_id(distinct_id)
        assert person is not None, "Person not found after first event"
        expected_after_first = {"plan": "free", "first_plan": "free"}
        self.assert_properties_contain(person.properties, expected_after_first)

        # Second event: combine all three operations
        logger.info("test_combined: capturing second event", distinct_id=distinct_id)
        second_props = {
            "$set": {"plan": "enterprise", "$test_version": 2},
            "$set_once": {"first_plan": "should_not_change"},
            "$unset": ["to_remove"],
        }
        second_event_uuid = self.client.capture_event(event_name, distinct_id, second_props)

        logger.info("test_combined: querying for second event", event_uuid=second_event_uuid)
        found_second = self.client.query_event_by_uuid(second_event_uuid)
        self.assert_event(found_second, second_event_uuid, event_name, distinct_id)

        logger.info("test_combined: querying for person after combined operations", distinct_id=distinct_id)
        person_after = self.client.query_person_by_distinct_id(distinct_id, min_version=2)
        assert person_after is not None, "Combined $set/$set_once/$unset not propagated within time budget"

        # $set overwrites, $set_once preserves existing + adds new, $unset removes
        expected_after_second = {
            "plan": "enterprise",  # $set overwrote
            "first_plan": "free",  # $set_once preserved original
        }
        self.assert_properties_contain(person_after.properties, expected_after_second)
        assert person_after.properties.get("to_remove") is None, "$unset should remove the property"
