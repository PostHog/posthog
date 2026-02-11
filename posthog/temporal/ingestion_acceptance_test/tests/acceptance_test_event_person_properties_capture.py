"""Event properties capture test - verifies $set, $set_once, and $unset person properties."""

import time
import uuid

from ..runner import AcceptanceTest


class TestPersonPropertiesCapture(AcceptanceTest):
    """Test event capture with person properties."""

    def test_set_person_properties(self) -> None:
        """Capture an event with $set person properties and verify they appear on person."""
        event_name = "$set_person_properties"
        distinct_id = str(uuid.uuid4())
        timestamp = time.time()
        expected_person_props = {"email": "test@example.com", "name": "Test User"}

        event_uuid = self.client.capture_event(
            event_name, distinct_id, {"$set": {**expected_person_props, "$test_timestamp": timestamp}}
        )
        found_event = self.client.query_event_by_uuid(event_uuid)
        found_event = self.assert_event(found_event, event_uuid, event_name, distinct_id)

        set_props = found_event.properties.get("$set")
        assert set_props is not None, "$set properties not found in event"
        self.assert_properties_contain(set_props, expected_person_props, "event $set")

        person = self.client.query_person_by_distinct_id(distinct_id)
        assert person is not None, "Person not found"
        self.assert_properties_contain(person.properties, expected_person_props, "person")

    def test_set_once_person_properties(self) -> None:
        """Verify $set_once only sets properties if they don't already exist."""
        event_name = "$set_once_person_properties"
        distinct_id = str(uuid.uuid4())
        initial_props = {"initial_referrer": "google"}

        # First event: set initial values with $set_once
        first_timestamp = time.time()
        first_event_uuid = self.client.capture_event(
            event_name, distinct_id, {"$set_once": initial_props, "$set": {"$test_timestamp": first_timestamp}}
        )
        found_first = self.client.query_event_by_uuid(first_event_uuid)
        self.assert_event(found_first, first_event_uuid, event_name, distinct_id)

        person = self.client.query_person_by_distinct_id(distinct_id)
        assert person is not None, "Person not found"
        self.assert_properties_contain(person.properties, initial_props, "person after first event")

        # Second event: try to overwrite with $set_once (should not change existing)
        second_timestamp = time.time()
        second_props = {
            "$set_once": {
                "initial_referrer": "facebook",  # should NOT overwrite
                "new_property": "should_be_set",  # should be set
            },
            "$set": {"$test_timestamp": second_timestamp},
        }
        second_event_uuid = self.client.capture_event(event_name, distinct_id, second_props)
        found_second = self.client.query_event_by_uuid(second_event_uuid)
        self.assert_event(found_second, second_event_uuid, event_name, distinct_id)

        person_after = self.client.query_person_by_distinct_id(distinct_id, min_timestamp=second_timestamp)
        assert person_after is not None
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
        first_timestamp = time.time()
        first_event_uuid = self.client.capture_event(
            event_name, distinct_id, {"$set": {**initial_props, "$test_timestamp": first_timestamp}}
        )
        found_first = self.client.query_event_by_uuid(first_event_uuid)
        self.assert_event(found_first, first_event_uuid, event_name, distinct_id)

        person = self.client.query_person_by_distinct_id(distinct_id)
        assert person is not None
        self.assert_properties_contain(person.properties, initial_props, "person after first event")

        # Second event: unset specific properties
        second_timestamp = time.time()
        second_event_uuid = self.client.capture_event(
            event_name, distinct_id, {"$unset": ["temporary_flag"], "$set": {"$test_timestamp": second_timestamp}}
        )
        found_second = self.client.query_event_by_uuid(second_event_uuid)
        self.assert_event(found_second, second_event_uuid, event_name, distinct_id)

        # Verify properties are removed, others remain
        person_after = self.client.query_person_by_distinct_id(distinct_id, min_timestamp=second_timestamp)
        assert person_after is not None
        assert person_after.properties.get("temporary_flag") is None, "$unset should remove the property"
        expected_remaining = {"email": "test@example.com", "name": "Test User"}
        self.assert_properties_contain(person_after.properties, expected_remaining, "remaining properties")

    def test_combined_set_set_once_unset(self) -> None:
        """Verify $set, $set_once, and $unset work together in same event."""
        event_name = "$set_set_once_unset_person_properties"
        distinct_id = str(uuid.uuid4())

        # First event: set initial properties
        first_timestamp = time.time()
        first_props = {
            "$set": {"plan": "free", "to_remove": "temporary", "$test_timestamp": first_timestamp},
            "$set_once": {"first_plan": "free"},
        }
        first_event_uuid = self.client.capture_event(event_name, distinct_id, first_props)
        found_first = self.client.query_event_by_uuid(first_event_uuid)
        self.assert_event(found_first, first_event_uuid, event_name, distinct_id)

        person = self.client.query_person_by_distinct_id(distinct_id)
        assert person is not None
        expected_after_first = {"plan": "free", "first_plan": "free"}
        self.assert_properties_contain(person.properties, expected_after_first)

        # Second event: combine all three operations
        second_timestamp = time.time()
        second_props = {
            "$set": {"plan": "enterprise", "$test_timestamp": second_timestamp},
            "$set_once": {"first_plan": "should_not_change"},
            "$unset": ["to_remove"],
        }
        second_event_uuid = self.client.capture_event(event_name, distinct_id, second_props)
        found_second = self.client.query_event_by_uuid(second_event_uuid)
        self.assert_event(found_second, second_event_uuid, event_name, distinct_id)

        person_after = self.client.query_person_by_distinct_id(distinct_id, min_timestamp=second_timestamp)
        assert person_after is not None

        # $set overwrites, $set_once preserves existing + adds new, $unset removes
        expected_after_second = {
            "plan": "enterprise",  # $set overwrote
            "first_plan": "free",  # $set_once preserved original
        }
        self.assert_properties_contain(person_after.properties, expected_after_second)
        assert person_after.properties.get("to_remove") is None, "$unset should remove the property"
