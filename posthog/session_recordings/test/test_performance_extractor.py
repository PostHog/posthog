import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase
from parameterized import parameterized

from posthog.session_recordings.performance_extractor import NetworkPerformanceExtractor


class TestNetworkPerformanceExtractor(TestCase):
    def setUp(self):
        self.mock_kafka_producer = MagicMock()
        self.extractor = NetworkPerformanceExtractor(kafka_producer=self.mock_kafka_producer)
        self.session_id = "test-session-123"
        self.team_id = 1
        self.distinct_id = "user-456"

    def test_extract_performance_events_from_empty_snapshots(self):
        """Test extraction with empty snapshots list."""
        events = self.extractor.extract_performance_events_from_snapshots(
            [], self.session_id, self.team_id, self.distinct_id
        )
        self.assertEqual(events, [])

    def test_extract_performance_events_filters_non_plugin_events(self):
        """Test that non-plugin events are filtered out."""
        snapshots = [
            {"type": 1, "data": {"some": "data"}},  # Not a plugin event
            {"type": 3, "data": {"source": 2}},  # Not a plugin event
            {"type": 6, "data": {"plugin": "other-plugin"}},  # Plugin but not network
        ]

        events = self.extractor.extract_performance_events_from_snapshots(
            snapshots, self.session_id, self.team_id, self.distinct_id
        )
        self.assertEqual(events, [])

    @parameterized.expand([
        ("rrweb/network@1",),
        ("posthog/network@1",),
    ])
    def test_extract_performance_events_from_rrweb_network_plugin(self, plugin_name):
        """Test extraction from RRWeb network plugin events."""
        test_request = {
            "name": "https://example.com/api/test",
            "entryType": "resource",
            "startTime": 100.5,
            "duration": 250.3,
            "responseStatus": 200,
            "transferSize": 1024,
            "initiatorType": "fetch",
        }

        snapshot = {
            "type": 6,
            "timestamp": 1640995200000,  # 2022-01-01T00:00:00Z
            "data": {
                "plugin": plugin_name,
                "payload": {
                    "requests": [test_request] if plugin_name == "rrweb/network@1" else test_request
                }
            }
        }

        events = self.extractor.extract_performance_events_from_snapshots(
            [snapshot], self.session_id, self.team_id, self.distinct_id
        )

        self.assertEqual(len(events), 1)
        event = events[0]

        # Check required fields
        self.assertEqual(event["session_id"], self.session_id)
        self.assertEqual(event["team_id"], self.team_id)
        self.assertEqual(event["distinct_id"], self.distinct_id)
        self.assertEqual(event["name"], "https://example.com/api/test")
        self.assertEqual(event["entry_type"], "resource")
        self.assertEqual(event["start_time"], 100.5)
        self.assertEqual(event["duration"], 250.3)
        self.assertEqual(event["response_status"], 200)
        self.assertEqual(event["transfer_size"], 1024)
        self.assertEqual(event["initiator_type"], "fetch")

        # Check UUID is generated
        self.assertIsInstance(event["uuid"], str)
        uuid.UUID(event["uuid"])  # Should not raise an exception

    def test_safe_type_conversions(self):
        """Test safe type conversion utility methods."""
        # Test _safe_float
        self.assertEqual(self.extractor._safe_float(123.45), 123.45)
        self.assertEqual(self.extractor._safe_float("123.45"), 123.45)
        self.assertEqual(self.extractor._safe_float(None), 0.0)
        self.assertEqual(self.extractor._safe_float("invalid"), 0.0)

        # Test _safe_int
        self.assertEqual(self.extractor._safe_int(123), 123)
        self.assertEqual(self.extractor._safe_int("123"), 123)
        self.assertEqual(self.extractor._safe_int(123.45), 123)
        self.assertEqual(self.extractor._safe_int(None), 0)
        self.assertEqual(self.extractor._safe_int("invalid"), 0)

    @parameterized.expand([
        (1640995200000, datetime(2022, 1, 1, 0, 0, 0)),  # Milliseconds
        (1640995200, datetime(2022, 1, 1, 0, 0, 0)),     # Seconds
        ("2022-01-01T00:00:00Z", datetime(2022, 1, 1, 0, 0, 0)),  # ISO string
        ("2022-01-01T00:00:00+00:00", datetime(2022, 1, 1, 0, 0, 0)),  # ISO with timezone
        (None, None),
        ("invalid", None),
    ])
    def test_convert_timestamp(self, input_timestamp, expected_output):
        """Test timestamp conversion."""
        result = self.extractor._convert_timestamp(input_timestamp)
        if expected_output is None:
            self.assertIsNone(result)
        else:
            self.assertEqual(result.replace(tzinfo=None), expected_output)

    def test_extract_window_id(self):
        """Test window ID extraction."""
        # Test with window_id present
        event = {"data": {"window_id": "window-123"}}
        self.assertEqual(self.extractor._extract_window_id(event), "window-123")

        # Test fallback to session_id
        event = {"data": {"session_id": "session-456"}}
        self.assertEqual(self.extractor._extract_window_id(event), "session-456")

        # Test fallback to unknown
        event = {"data": {}}
        self.assertEqual(self.extractor._extract_window_id(event), "unknown")

    def test_generate_pageview_id(self):
        """Test pageview ID generation."""
        # Same URL and timestamp should generate same ID
        id1 = self.extractor._generate_pageview_id("https://example.com/page", 1234567890)
        id2 = self.extractor._generate_pageview_id("https://example.com/page", 1234567890)
        self.assertEqual(id1, id2)

        # Different URL should generate different ID
        id3 = self.extractor._generate_pageview_id("https://example.com/other", 1234567890)
        self.assertNotEqual(id1, id3)

        # Query parameters should be stripped
        id4 = self.extractor._generate_pageview_id("https://example.com/page?param=value", 1234567890)
        self.assertEqual(id1, id4)

    def test_send_performance_events_to_kafka(self):
        """Test sending events to Kafka."""
        events = [
            {
                "uuid": str(uuid.uuid4()),
                "session_id": self.session_id,
                "team_id": self.team_id,
                "name": "https://example.com/api/test",
                "response_status": 200,
            }
        ]

        self.extractor.send_performance_events_to_kafka(events)

        # Verify Kafka producer was called
        self.mock_kafka_producer.produce.assert_called_once()
        call_args = self.mock_kafka_producer.produce.call_args

        self.assertEqual(call_args.kwargs["topic"], "clickhouse_performance_events")
        self.assertEqual(call_args.kwargs["key"], self.session_id)

        # Verify data can be parsed as JSON
        sent_data = json.loads(call_args.kwargs["data"])
        self.assertEqual(sent_data["session_id"], self.session_id)

    @patch("posthog.session_recordings.performance_extractor.logger")
    def test_kafka_error_handling(self, mock_logger):
        """Test error handling when Kafka fails."""
        self.mock_kafka_producer.produce.side_effect = Exception("Kafka error")

        events = [{"session_id": self.session_id, "name": "test"}]
        self.extractor.send_performance_events_to_kafka(events)

        # Should log error but not raise
        mock_logger.error.assert_called_once()

    def test_process_session_recording_integration(self):
        """Test the full process_session_recording method."""
        snapshots = [
            {
                "type": 6,
                "timestamp": 1640995200000,
                "data": {
                    "plugin": "rrweb/network@1",
                    "payload": {
                        "requests": [
                            {
                                "name": "https://example.com/api/test",
                                "entryType": "resource",
                                "responseStatus": 200,
                            }
                        ]
                    }
                }
            }
        ]

        count = self.extractor.process_session_recording(
            snapshots, self.session_id, self.team_id, self.distinct_id
        )

        self.assertEqual(count, 1)
        self.mock_kafka_producer.produce.assert_called_once()

    def test_process_session_recording_with_invalid_data(self):
        """Test processing with invalid snapshot data."""
        snapshots = [
            None,  # Invalid snapshot
            {"type": "invalid"},  # Invalid type
            {
                "type": 6,
                "data": {
                    "plugin": "rrweb/network@1",
                    "payload": {
                        "requests": [
                            {"invalid": "request"}  # Request missing required fields
                        ]
                    }
                }
            }
        ]

        count = self.extractor.process_session_recording(
            snapshots, self.session_id, self.team_id, self.distinct_id
        )

        # Should handle errors gracefully and return 0
        self.assertEqual(count, 0)

    def test_complex_rrweb_request_mapping(self):
        """Test mapping of complex RRWeb request with all timing fields."""
        test_request = {
            "name": "https://api.example.com/v1/users",
            "entryType": "resource",
            "startTime": 1234.5,
            "duration": 567.8,
            "redirectStart": 0,
            "redirectEnd": 0,
            "fetchStart": 1234.5,
            "domainLookupStart": 1234.6,
            "domainLookupEnd": 1235.1,
            "connectStart": 1235.1,
            "secureConnectionStart": 1235.2,
            "connectEnd": 1236.0,
            "requestStart": 1236.1,
            "responseStart": 1750.2,
            "responseEnd": 1802.3,
            "decodedBodySize": 2048,
            "encodedBodySize": 1024,
            "transferSize": 1100,
            "initiatorType": "xmlhttprequest",
            "nextHopProtocol": "h2",
            "renderBlockingStatus": "non-blocking",
            "responseStatus": 201,
        }

        snapshot = {
            "type": 6,
            "timestamp": 1640995200000,
            "data": {
                "plugin": "rrweb/network@1",
                "payload": {"requests": [test_request]}
            }
        }

        events = self.extractor.extract_performance_events_from_snapshots(
            [snapshot], self.session_id, self.team_id, self.distinct_id
        )

        self.assertEqual(len(events), 1)
        event = events[0]

        # Verify all timing fields are mapped correctly
        self.assertEqual(event["start_time"], 1234.5)
        self.assertEqual(event["duration"], 567.8)
        self.assertEqual(event["fetch_start"], 1234.5)
        self.assertEqual(event["domain_lookup_start"], 1234.6)
        self.assertEqual(event["domain_lookup_end"], 1235.1)
        self.assertEqual(event["connect_start"], 1235.1)
        self.assertEqual(event["secure_connection_start"], 1235.2)
        self.assertEqual(event["connect_end"], 1236.0)
        self.assertEqual(event["request_start"], 1236.1)
        self.assertEqual(event["response_start"], 1750.2)
        self.assertEqual(event["response_end"], 1802.3)

        # Verify size fields
        self.assertEqual(event["decoded_body_size"], 2048)
        self.assertEqual(event["encoded_body_size"], 1024)
        self.assertEqual(event["transfer_size"], 1100)

        # Verify metadata fields
        self.assertEqual(event["initiator_type"], "xmlhttprequest")
        self.assertEqual(event["next_hop_protocol"], "h2")
        self.assertEqual(event["render_blocking_status"], "non-blocking")
        self.assertEqual(event["response_status"], 201)

    def test_posthog_network_plugin_mapping(self):
        """Test mapping from PostHog network plugin format."""
        payload = {
            "name": "https://api.example.com/endpoint",
            "entry_type": "resource",
            "start_time": 100.0,
            "response_status": 404,
            "transfer_size": 512,
            # Test snake_case field mapping
            "decoded_body_size": 1024,
            "initiator_type": "fetch",
        }

        snapshot = {
            "type": 6,
            "timestamp": 1640995200000,
            "data": {
                "plugin": "posthog/network@1",
                "payload": payload
            }
        }

        events = self.extractor.extract_performance_events_from_snapshots(
            [snapshot], self.session_id, self.team_id, self.distinct_id
        )

        self.assertEqual(len(events), 1)
        event = events[0]

        # Verify PostHog format fields are mapped correctly
        self.assertEqual(event["name"], "https://api.example.com/endpoint")
        self.assertEqual(event["entry_type"], "resource")
        self.assertEqual(event["start_time"], 100.0)
        self.assertEqual(event["response_status"], 404)
        self.assertEqual(event["transfer_size"], 512)
        self.assertEqual(event["decoded_body_size"], 1024)
        self.assertEqual(event["initiator_type"], "fetch")
