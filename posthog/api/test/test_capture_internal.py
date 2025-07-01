from datetime import datetime, UTC
from django.test.client import Client
from unittest.mock import patch, MagicMock

from posthog.api.capture import new_capture_internal, CaptureInternalError
from posthog.test.base import BaseTest
from posthog.settings.ingestion import (
    NEW_CAPTURE_RUST_BASE_URL,
    NEW_ANALYTICS_CAPTURE_ENDPOINT,
    REPLAY_CAPTURE_ENDPOINT,
)


class TestCaptureInternal(BaseTest):
    """
    Tests the `new_capture_internal` function.
    """

    def setUp(self):
        super().setUp()  # we will be calling
        self.client = Client(enforce_csrf_checks=True)

    @patch("posthog.api.capture.Session")
    def test_new_capture_internal(self, mock_session_class):
        token = "abc123"
        distinct_id = "xyz987"
        event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        test_event = {
            "event": event_name,
            "distinct_id": distinct_id,
            "api_token": token,
            "timestamp": timestamp,
            "properties": {
                "$current_url": "https://example.com",
                "$ip": "127.0.0.1",
                "$lib": "python",
                "$lib_version": "1.0.0",
                "$screen_width": 1920,
                "$screen_height": 1080,
                "some_custom_property": True,
            },
        }

        spied_calls = []

        def spy_post(*args, **kwargs):
            spied_calls.append(
                {
                    "url": args[0],
                    "event_payload": kwargs["json"],
                }
            )
            mock_response = MagicMock()
            mock_response.status_code = 200
            return mock_response

        mock_session = MagicMock()
        mock_session.return_value.post.side_effect = spy_post
        mock_session_class.return_value.__enter__.return_value = mock_session

        response = new_capture_internal(token, distinct_id, test_event)

        assert response.status_code == 200
        assert len(spied_calls) == 1
        assert NEW_CAPTURE_RUST_BASE_URL in spied_calls[0]["url"]
        assert NEW_ANALYTICS_CAPTURE_ENDPOINT in spied_calls[0]["url"]
        assert spied_calls[0]["event_payload"]["event"] == event_name
        assert spied_calls[0]["event_payload"]["distinct_id"] == distinct_id
        assert spied_calls[0]["event_payload"]["api_token"] == token
        assert spied_calls[0]["event_payload"]["timestamp"] == timestamp
        assert len(spied_calls[0]["event_payload"]["properties"]) == len(test_event["properties"])

    @patch("posthog.api.capture.Session")
    def test_new_capture_internal_replay(self, mock_session_class):
        token = "abc123"
        distinct_id = "xyz987"
        event_name = "$snapshot"
        timestamp = datetime.now(UTC).isoformat()

        test_replay_event = {
            "event": event_name,
            "distinct_id": distinct_id,
            "api_token": token,
            "timestamp": timestamp,
            "properties": {
                "$current_url": "https://example.com",
                "$ip": "127.0.0.1",
                "$lib": "python",
                "$lib_version": "1.0.0",
                "$screen_width": 1920,
                "$screen_height": 1080,
                "some_custom_property": True,
            },
        }

        spied_calls = []

        def spy_replay_post(*args, **kwargs):
            spied_calls.append(
                {
                    "url": args[0],
                    "event_payload": kwargs["json"],
                }
            )
            mock_response = MagicMock()
            mock_response.status_code = 200
            return mock_response

        mock_session = MagicMock()
        mock_session.return_value.post.side_effect = spy_replay_post
        mock_session_class.return_value.__enter__.return_value = mock_session

        response = new_capture_internal(token, distinct_id, test_replay_event)

        assert response.status_code == 200
        assert len(spied_calls) == 1
        assert NEW_CAPTURE_RUST_BASE_URL in spied_calls[0]["url"]
        assert REPLAY_CAPTURE_ENDPOINT in spied_calls[0]["url"]
        assert spied_calls[0]["event_payload"]["event"] == event_name
        assert spied_calls[0]["event_payload"]["distinct_id"] == distinct_id
        assert spied_calls[0]["event_payload"]["api_token"] == token
        assert spied_calls[0]["event_payload"]["timestamp"] == timestamp
        assert len(spied_calls[0]["event_payload"]["properties"]) == len(test_replay_event["properties"])

    def test_new_capture_internal_invalid_token(self):
        token = None
        distinct_id = "xyz987"
        event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        # no fallback token provided in event payload
        test_event = {
            "event": event_name,
            "distinct_id": distinct_id,
            "timestamp": timestamp,
            "properties": {
                "$current_url": "https://example.com",
                "$ip": "127.0.0.1",
                "$lib": "python",
                "$lib_version": "1.0.0",
                "$screen_width": 1920,
                "$screen_height": 1080,
                "some_custom_property": True,
            },
        }

        with self.assertRaises(CaptureInternalError) as e:
            new_capture_internal(token, distinct_id, test_event)
            assert str(e.value) == "API token is required"

    def test_new_capture_internal_invalid_distinct_id(self):
        token = "abc123"
        distinct_id = None
        event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        # no fallback distinct ID provided in event payload (top-level or in properties)
        test_event = {
            "event": event_name,
            "api_token": token,
            "timestamp": timestamp,
            "properties": {
                "$current_url": "https://example.com",
                "$ip": "127.0.0.1",
                "$lib": "python",
                "$lib_version": "1.0.0",
                "$screen_width": 1920,
                "$screen_height": 1080,
                "some_custom_property": True,
            },
        }

        with self.assertRaises(CaptureInternalError) as e:
            new_capture_internal(token, distinct_id, test_event)
            assert str(e.value) == "distinct ID is required"

    def test_new_capture_internal_invalid_event_name(self):
        token = "abc123"
        distinct_id = "xyz678"
        timestamp = datetime.now(UTC).isoformat()

        # no event name supplied in payload
        test_event = {
            "api_token": token,
            "timestamp": timestamp,
            "properties": {
                "$current_url": "https://example.com",
                "$ip": "127.0.0.1",
                "$lib": "python",
                "$lib_version": "1.0.0",
                "$screen_width": 1920,
                "$screen_height": 1080,
                "some_custom_property": True,
            },
        }

        with self.assertRaises(CaptureInternalError) as e:
            new_capture_internal(token, distinct_id, test_event)
            assert str(e.value) == "event name is required"
