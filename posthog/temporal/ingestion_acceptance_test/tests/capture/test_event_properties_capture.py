"""Event properties capture test - verifies $set and $set_once person properties."""

import uuid

from ...client import PostHogClient
from ...config import Config


class TestEventPropertiesCapture:
    """Test event capture with person properties."""

    def test_capture_event_with_person_properties(self, client: PostHogClient, config: Config) -> None:
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
            "$set_once": {
                "initial_referrer": "https://google.com",
                "created_at": "2024-01-15T10:30:00Z",
            },
        }

        event_uuid = client.capture_event(
            event_name=event_name,
            distinct_id=distinct_id,
            properties=properties,
        )

        found_event = client.query_event_by_uuid(
            event_uuid=event_uuid,
            timeout_seconds=config.event_timeout_seconds,
        )

        assert found_event is not None, (
            f"Event with UUID '{event_uuid}' not found within {config.event_timeout_seconds}s timeout"
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

        set_once_props = found_event.properties.get("$set_once")
        assert set_once_props is not None, "$set_once properties not found in event"
        assert set_once_props.get("initial_referrer") == "https://google.com"
        assert set_once_props.get("created_at") == "2024-01-15T10:30:00Z"
