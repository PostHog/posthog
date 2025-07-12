from typing import Any
from datetime import datetime, UTC
from unittest.mock import patch, MagicMock
from uuid import uuid4

from posthog.api.capture import new_capture_internal, new_capture_batch_internal, CaptureInternalError
from posthog.test.base import BaseTest
from posthog.settings.ingestion import (
    CAPTURE_INTERNAL_URL,
    CAPTURE_REPLAY_INTERNAL_URL,
    NEW_ANALYTICS_CAPTURE_ENDPOINT,
    REPLAY_CAPTURE_ENDPOINT,
)


class InstallCapturePostSpy:
    def __init__(self, mock_session_class, status_code=200):
        self.status_code = status_code
        self.spied_calls: list[dict[str, Any]] = []

        def spy_post(*args, **kwargs):
            self.spied_calls.append(
                {
                    "url": args[0],
                    "event_payload": kwargs["json"],
                }
            )
            mock_response = MagicMock()
            mock_response.status_code = self.status_code
            return mock_response

        mock_session = MagicMock()
        mock_session.post.side_effect = spy_post
        mock_session_class.return_value.__enter__.return_value = mock_session

    def get_calls(self) -> list[dict[str, Any]]:
        return self.spied_calls


class TestCaptureInternal(BaseTest):
    """
    Tests the `new_capture_internal` function.
    """

    def setUp(self):
        super().setUp()

    @patch("posthog.api.capture.Session")
    def test_new_capture_internal(self, mock_session_class):
        token = "abc123"
        distinct_id = "xyz987"
        event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        test_event = {
            "event": event_name,
            "distinct_id": distinct_id,
            "api_key": token,
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

        spy = InstallCapturePostSpy(mock_session_class)
        response = new_capture_internal(token, distinct_id, test_event)
        assert response.status_code == 200

        spied_calls = spy.get_calls()
        assert len(spied_calls) == 1
        assert f"{CAPTURE_INTERNAL_URL}{NEW_ANALYTICS_CAPTURE_ENDPOINT}" in spied_calls[0]["url"]
        assert spied_calls[0]["event_payload"]["event"] == event_name
        assert spied_calls[0]["event_payload"]["distinct_id"] == distinct_id
        assert spied_calls[0]["event_payload"]["api_key"] == token
        assert spied_calls[0]["event_payload"]["timestamp"] == timestamp
        # note: event payload passed to new_capture_internal is mutated. here we inject a source marker
        assert spied_calls[0]["event_payload"]["properties"]["capture_internal"] is True
        assert len(spied_calls[0]["event_payload"]["properties"]) == len(test_event["properties"])
        # when process_person_profile is False, new_capture_internal explicitly sets this on the event
        assert spied_calls[0]["event_payload"]["properties"].get("$process_person_profile", None) is not None
        assert spied_calls[0]["event_payload"]["properties"]["$process_person_profile"] is False

    @patch("posthog.api.capture.Session")
    def test_new_capture_internal_with_persons_processing(self, mock_session_class):
        token = "abc123"
        distinct_id = "xyz987"
        event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        test_event = {
            "event": event_name,
            "distinct_id": distinct_id,
            "api_key": token,
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

        spy = InstallCapturePostSpy(mock_session_class)
        response = new_capture_internal(token, distinct_id, test_event, True)
        assert response.status_code == 200

        spied_calls = spy.get_calls()
        assert len(spied_calls) == 1
        assert f"{CAPTURE_INTERNAL_URL}{NEW_ANALYTICS_CAPTURE_ENDPOINT}" in spied_calls[0]["url"]
        assert spied_calls[0]["event_payload"]["event"] == event_name
        assert spied_calls[0]["event_payload"]["distinct_id"] == distinct_id
        assert spied_calls[0]["event_payload"]["api_key"] == token
        assert spied_calls[0]["event_payload"]["timestamp"] == timestamp
        assert spied_calls[0]["event_payload"]["properties"]["capture_internal"] is True
        assert len(spied_calls[0]["event_payload"]["properties"]) == len(test_event["properties"])
        # when new_capture_internal is called with process_person_profile == True, we don't alter the event payload
        assert spied_calls[0]["event_payload"]["properties"].get("$process_person_profile", None) is None

    @patch("posthog.api.capture.Session")
    def test_new_capture_internal_with_capture_post_server_error(self, mock_session_class):
        token = "abc123"
        distinct_id = "xyz987"
        event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        test_event = {
            "event": event_name,
            "distinct_id": distinct_id,
            "api_key": token,
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

        InstallCapturePostSpy(mock_session_class, status_code=503)
        response = new_capture_internal(token, distinct_id, test_event, False)
        assert response.status_code == 503
        # note: retry mechanism is disabled since we mocked requests.Session

    @patch("posthog.api.capture.Session")
    def test_new_capture_internal_replay(self, mock_session_class):
        token = "abc123"
        distinct_id = "xyz987"
        event_name = "$snapshot"
        timestamp = datetime.now(UTC).isoformat()

        test_replay_event = {
            "event": event_name,
            "distinct_id": distinct_id,
            "api_key": token,
            "timestamp": timestamp,
            "properties": {
                "$screen_density": 2.75,
                "$screen_height": 2154,
                "$screen_width": 1080,
                "$app_version": "1.0",
                "$app_namespace": "com.posthog.android.sample",
                "$app_build": 1,
                "$app_name": "PostHog Android Sample",
                "$device_manufacturer": "Google",
                "$device_model": "sdk_gphone64_arm64",
                "$device_name": "emu64a",
                "$device_type": "Mobile",
                "$os_name": "Android",
                "$os_version": "14",
                "$lib": "posthog-android",
                "$lib_version": "3.0.0-beta.3",
                "$is_emulator": True,
                "$locale": "en-US",
                "$user_agent": "Dalvik/2.1.0 (Linux; U; Android 14; sdk_gphone64_arm64 Build/UPB5.230623.003)",
                "$timezone": "Europe/Vienna",
                "$network_wifi": True,
                "$network_bluetooth": False,
                "$network_cellular": False,
                "$network_carrier": "T-Mobile",
                "$snapshot_data": [
                    {"timestamp": 1699354586963, "type": 0},
                    {"timestamp": 1699354586963, "type": 1},
                    {
                        "data": {"href": "http://localhost", "width": 1080, "height": 2220},
                        "timestamp": 1699354586963,
                        "type": 4,
                    },
                    {
                        "data": {
                            "node": {
                                "id": 1,
                                "type": 0,
                                "childNodes": [
                                    {"type": 1, "name": "html", "id": 2, "childNodes": []},
                                    {
                                        "id": 3,
                                        "type": 2,
                                        "tagName": "html",
                                        "childNodes": [
                                            {
                                                "id": 5,
                                                "type": 2,
                                                "tagName": "body",
                                                "childNodes": [
                                                    {
                                                        "type": 2,
                                                        "tagName": "canvas",
                                                        "id": 7,
                                                        "attributes": {
                                                            "id": "canvas",
                                                            "width": "1080",
                                                            "height": "2220",
                                                        },
                                                        "childNodes": [],
                                                    }
                                                ],
                                            }
                                        ],
                                    },
                                ],
                                "initialOffset": {"left": 0, "top": 0},
                            }
                        },
                        "timestamp": 1699354586963,
                        "type": 2,
                    },
                ],
                "$session_id": "bceaa9ce-dc9d-4728-8a90-4a7c249604b1",
                "$window_id": "31bfffdc-79fc-4504-9ff4-0216a58bf7f6",
            },
        }

        spy = InstallCapturePostSpy(mock_session_class)
        response = new_capture_internal(token, distinct_id, test_replay_event)
        assert response.status_code == 200

        spied_calls = spy.get_calls()
        assert len(spied_calls) == 1
        assert f"{CAPTURE_REPLAY_INTERNAL_URL}{REPLAY_CAPTURE_ENDPOINT}" in spied_calls[0]["url"]
        assert spied_calls[0]["event_payload"]["event"] == event_name
        assert spied_calls[0]["event_payload"]["distinct_id"] == distinct_id
        assert spied_calls[0]["event_payload"]["api_key"] == token
        assert spied_calls[0]["event_payload"]["timestamp"] == timestamp
        assert spied_calls[0]["event_payload"]["properties"]["capture_internal"] is True
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
        assert str(e.exception) == "capture_internal: API token is required"

    def test_new_capture_internal_invalid_distinct_id(self):
        token = "abc123"
        distinct_id = None
        event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        # no fallback distinct ID provided in event payload (top-level or in properties)
        test_event = {
            "event": event_name,
            "api_key": token,
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
        assert str(e.exception) == "capture_internal: distinct ID is required"

    def test_new_capture_internal_invalid_event_name(self):
        token = "abc123"
        distinct_id = "xyz678"
        timestamp = datetime.now(UTC).isoformat()

        # no event name supplied in payload
        test_event = {
            "api_key": token,
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
        assert str(e.exception) == "capture_internal: event name is required"

    @patch("posthog.api.capture.Session")
    def test_new_capture_batch_internal(self, mock_session_class):
        token = "abc123"
        base_event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        test_events = []
        for i in range(10):
            test_events.append(
                {
                    "event": f"{base_event_name}_{i}",
                    "distinct_id": str(uuid4()),
                    "api_key": token,
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
            )

        spy = InstallCapturePostSpy(mock_session_class)
        resp_futures = new_capture_batch_internal(test_events, token, False)

        for future in resp_futures:
            resp = future.result()
            assert resp.status_code == 200

        spied_calls = spy.get_calls()
        assert len(spied_calls) == 10

        # ensure stable test assertions against test_events list
        spied_calls = sorted(spied_calls, key=lambda evt: evt["event_payload"]["event"])

        for i in range(10):
            assert f"{CAPTURE_INTERNAL_URL}{NEW_ANALYTICS_CAPTURE_ENDPOINT}" in spied_calls[i]["url"]
            assert spied_calls[i]["event_payload"]["event"] == f"{base_event_name}_{i}"
            assert spied_calls[i]["event_payload"]["distinct_id"] == test_events[i]["distinct_id"]
            assert spied_calls[i]["event_payload"]["api_key"] == token
            assert spied_calls[i]["event_payload"]["timestamp"] == timestamp
            assert len(spied_calls[i]["event_payload"]["properties"]) == len(test_events[i]["properties"])
            # every event in the batch should be marked asinternally-sourced
            assert spied_calls[i]["event_payload"]["properties"]["capture_internal"] is True
            # since process_person_profile is False, it should have been injected into the event
            assert spied_calls[i]["event_payload"]["properties"].get("$process_person_profile", None) is not None
            assert spied_calls[i]["event_payload"]["properties"]["$process_person_profile"] is False

    def test_new_capture_batch_internal_invalid_payload(self):
        token = "abc123"
        base_event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        test_events = []
        for i in range(3):
            test_events.append(
                {
                    "event": f"{base_event_name}_{i}",
                    # without a distinct_id on each event, this won't go well
                    "api_key": token,
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
            )

        resp_futures = new_capture_batch_internal(test_events, token, False)
        assert len(resp_futures) == 3

        for future in resp_futures:
            with self.assertRaises(CaptureInternalError) as e:
                future.result()
            assert str(e.exception) == "capture_internal: distinct ID is required"

    @patch("posthog.api.capture.Session")
    def test_new_capture_batch_internal_bad_req(self, mock_session_class):
        token = "abc123"
        base_event_name = "test_event"
        timestamp = datetime.now(UTC).isoformat()

        test_events = []
        for i in range(3):
            test_events.append(
                {
                    "event": f"{base_event_name}_{i}",
                    "distinct_id": "xyz456",
                    "api_key": token,
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
            )

        InstallCapturePostSpy(mock_session_class, status_code=400)
        resp_futures = new_capture_batch_internal(test_events, token, False)
        assert len(resp_futures) == 3

        for future in resp_futures:
            resp = future.result()
            assert resp.status_code == 400
