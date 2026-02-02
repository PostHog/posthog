"""Basic event capture test - sends an event and verifies it appears in queries."""

import uuid

from ..runner import AcceptanceTest


class TestBasicCapture(AcceptanceTest):
    """Test basic event capture and retrieval flow."""

    def test_capture_event_and_query(self) -> None:
        """Capture a basic event and verify it appears in HogQL queries."""
        event_name = "$test_basic_capture"
        distinct_id = str(uuid.uuid4())

        event_uuid = self.client.capture_event(event_name=event_name, distinct_id=distinct_id)

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
