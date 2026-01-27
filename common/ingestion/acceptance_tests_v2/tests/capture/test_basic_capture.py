"""Basic event capture test - sends an event and verifies it appears in queries."""

import uuid

from ...client import PostHogClient
from ...config import Config


class TestBasicCapture:
    """Test basic event capture and retrieval flow."""

    def test_capture_event_and_query(self, client: PostHogClient, config: Config) -> None:
        """Capture a single event via /capture and verify it appears in HogQL queries."""
        test_run_id = uuid.uuid4().hex[:8]
        event_name = f"$test_capture_{test_run_id}"
        distinct_id = f"test_user_{test_run_id}"

        properties = {
            "test_run_id": test_run_id,
            "test_string": "hello world",
            "test_number": 42,
            "test_bool": True,
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
        assert found_event.properties.get("test_string") == "hello world"
        assert found_event.properties.get("test_number") == 42
        assert found_event.properties.get("test_bool") is True
