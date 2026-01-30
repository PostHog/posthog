"""Event properties capture test - verifies $set and $set_once person properties."""

import uuid

from ..runner import AcceptanceTest


class TestEventPropertiesCapture(AcceptanceTest):
    """Test event capture with person properties."""

    def test_capture_event_with_person_properties(self) -> None:
        """Capture an event with $set and $set_once person properties."""
        test_run_id = uuid.uuid4().hex[:8]
        event_name = "$test_person_props"
        distinct_id = f"test_user_{test_run_id}"

        properties = {
            "test_run_id": test_run_id,
            "$set": {
                "email": f"test_{test_run_id}@example.com",
                "name": "Test User",
                "plan": "enterprise",
            },
        }

        event_uuid = self.client.capture_event(
            event_name=event_name,
            distinct_id=distinct_id,
            properties=properties,
        )

        found_event = self.client.query_event_by_uuid(
            event_uuid=event_uuid,
            timeout_seconds=self.config.event_timeout_seconds,
        )

        assert found_event is not None, (
            f"Event with UUID '{event_uuid}' not found within {self.config.event_timeout_seconds}s timeout"
        )
        assert found_event.uuid == event_uuid
        assert found_event.event == event_name
        assert found_event.distinct_id == distinct_id
        assert found_event.properties.get("test_run_id") == test_run_id

        set_props = found_event.properties.get("$set")
        assert set_props is not None, "$set properties not found in event"
        assert set_props.get("email") == f"test_{test_run_id}@example.com"
        assert set_props.get("name") == "Test User"
        assert set_props.get("plan") == "enterprise"

        person = self.client.query_person_by_distinct_id(
            distinct_id=distinct_id,
            timeout_seconds=self.config.event_timeout_seconds,
        )

        assert person is not None, f"Person with distinct_id '{distinct_id}' not found"
        assert person.properties.get("email") == f"test_{test_run_id}@example.com"
        assert person.properties.get("name") == "Test User"
        assert person.properties.get("plan") == "enterprise"
