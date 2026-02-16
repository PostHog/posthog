"""Basic event capture test - sends an event and verifies it appears in queries."""

import uuid

from ..runner import AcceptanceTest


class TestBasicCapture(AcceptanceTest):
    """Test basic event capture and retrieval flow."""

    def test_capture_event(self) -> None:
        """Capture a basic event and verify it appears in HogQL queries."""
        event_name = "$test_basic_capture"
        distinct_id = str(uuid.uuid4())

        event_uuid = self.client.capture_event(event_name, distinct_id)
        found_event = self.client.query_event_by_uuid(event_uuid)
        self.assert_event(found_event, event_uuid, event_name, distinct_id)

    def test_capture_event_with_properties(self) -> None:
        """Capture an event with custom properties and verify they are stored."""
        event_name = "$test_custom_props"
        distinct_id = str(uuid.uuid4())
        properties = {
            "button_name": "signup",
            "page_url": "https://example.com/signup",
            "referrer": "google",
        }

        event_uuid = self.client.capture_event(event_name, distinct_id, properties)
        found_event = self.client.query_event_by_uuid(event_uuid)
        found_event = self.assert_event(found_event, event_uuid, event_name, distinct_id)
        self.assert_properties_contain(found_event.properties, properties)
