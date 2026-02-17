"""
Tests for point-in-time person properties building functionality.
"""

import json
from datetime import UTC, datetime
from typing import cast

from unittest.mock import patch

from django.test import TestCase

from posthog.models.person.point_in_time_properties import build_person_properties_at_time


class TestPointInTimeProperties(TestCase):
    def test_build_person_properties_at_time_validation(self):
        """Test input validation for build_person_properties_at_time."""
        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Test invalid team_id
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(0, timestamp, ["user123"])
        self.assertIn("team_id must be a positive integer", str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(-1, timestamp, ["user123"])
        self.assertIn("team_id must be a positive integer", str(cm.exception))

        # Test invalid timestamp
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(1, cast(datetime, "2023-01-01"), ["user123"])
        self.assertIn("timestamp must be a datetime object", str(cm.exception))

        # Test invalid distinct_ids (empty list)
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(1, timestamp, [])
        self.assertIn("distinct_ids must be a non-empty list", str(cm.exception))

        # Test invalid distinct_ids (not a list)
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(1, timestamp, "not_a_list")
        self.assertIn("distinct_ids must be a non-empty list", str(cm.exception))

        # Test invalid distinct_ids (contains empty string)
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(1, timestamp, ["user123", ""])
        self.assertIn("All distinct_ids must be non-empty strings", str(cm.exception))

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_empty_result(self, mock_sync_execute):
        """Test building properties when no events exist."""
        mock_sync_execute.return_value = []

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"])

        self.assertEqual(result, {})
        mock_sync_execute.assert_called_once()

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_single_set(self, mock_sync_execute):
        """Test building properties with a single $set event."""
        # Mock ClickHouse response with a single $set event
        properties = {"$set": {"name": "John Doe", "email": "john@example.com"}}
        # ClickHouse toJSONString() returns double-encoded JSON
        double_encoded_json = json.dumps(json.dumps(properties))
        mock_sync_execute.return_value = [(double_encoded_json, datetime(2023, 1, 1, 10, 0, 0), "$set")]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"])

        expected = {"name": "John Doe", "email": "john@example.com"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_multiple_sets(self, mock_sync_execute):
        """Test building properties with multiple $set events applied chronologically."""
        # Mock ClickHouse response with multiple $set events
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            (json.dumps(json.dumps({"$set": {"name": "John", "age": 25}})), datetime(2023, 1, 1, 9, 0, 0), "$set"),
            (
                json.dumps(json.dumps({"$set": {"name": "John Doe", "location": "SF"}})),
                datetime(2023, 1, 1, 10, 0, 0),
                "$pageview",
            ),
            (json.dumps(json.dumps({"$set": {"age": 26}})), datetime(2023, 1, 1, 11, 0, 0), "$set"),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"])

        expected = {"name": "John Doe", "age": 26, "location": "SF"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_malformed_json(self, mock_sync_execute):
        """Test handling of malformed JSON in event properties."""
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            ("invalid json", datetime(2023, 1, 1, 9, 0, 0), "$set"),
            (json.dumps(json.dumps({"$set": {"name": "John"}})), datetime(2023, 1, 1, 10, 0, 0), "$set"),
            (json.dumps(json.dumps({"no_set_key": "value"})), datetime(2023, 1, 1, 11, 0, 0), "$pageview"),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"])

        # Should only get the valid $set event
        expected = {"name": "John"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_clickhouse_error(self, mock_sync_execute):
        """Test handling of ClickHouse query errors."""
        mock_sync_execute.side_effect = Exception("ClickHouse connection failed")

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)

        with self.assertRaises(Exception) as cm:
            build_person_properties_at_time(1, timestamp, ["user123"])

        self.assertIn("Failed to query ClickHouse events", str(cm.exception))


class TestPointInTimePropertiesWithSetOnce(TestCase):
    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_with_set_once_basic(self, mock_sync_execute):
        """Test $set_once operations only set properties that don't exist."""
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            (json.dumps(json.dumps({"$set": {"name": "John"}})), datetime(2023, 1, 1, 9, 0, 0), "$set"),
            (
                json.dumps(json.dumps({"$set_once": {"name": "Jane", "email": "jane@example.com"}})),
                datetime(2023, 1, 1, 10, 0, 0),
                "$set_once",
            ),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"], include_set_once=True)

        # name should remain "John" (not overwritten by $set_once)
        # email should be set by $set_once since it didn't exist
        expected = {"name": "John", "email": "jane@example.com"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_with_set_once_order_matters(self, mock_sync_execute):
        """Test that order of $set and $set_once operations matters."""
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            (
                json.dumps(json.dumps({"$set_once": {"name": "Jane", "email": "jane@example.com"}})),
                datetime(2023, 1, 1, 9, 0, 0),
                "$set_once",
            ),
            (json.dumps(json.dumps({"$set": {"name": "John"}})), datetime(2023, 1, 1, 10, 0, 0), "$set"),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"], include_set_once=True)

        # $set_once sets name first, then $set overwrites it
        expected = {"name": "John", "email": "jane@example.com"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_with_set_once_multiple_set_once(self, mock_sync_execute):
        """Test multiple $set_once operations - only first one should apply per property."""
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            (
                json.dumps(json.dumps({"$set_once": {"name": "First", "email": "first@example.com"}})),
                datetime(2023, 1, 1, 9, 0, 0),
                "$set_once",
            ),
            (
                json.dumps(json.dumps({"$set_once": {"name": "Second", "location": "SF"}})),
                datetime(2023, 1, 1, 10, 0, 0),
                "$set_once",
            ),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"], include_set_once=True)

        # First $set_once should win for name, second should set location
        expected = {"name": "First", "email": "first@example.com", "location": "SF"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_with_distinct_ids_direct(self, mock_sync_execute):
        """Test building properties using distinct_ids parameter directly."""
        # Mock ClickHouse response with a single $set event
        properties = {"$set": {"name": "Jane Doe", "email": "jane@example.com"}}
        # ClickHouse toJSONString() returns double-encoded JSON
        double_encoded_json = json.dumps(json.dumps(properties))
        mock_sync_execute.return_value = [(double_encoded_json, datetime(2023, 1, 1, 10, 0, 0), "$set")]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, distinct_ids=["user123", "user456", "user789"])

        expected = {"name": "Jane Doe", "email": "jane@example.com"}
        self.assertEqual(result, expected)

        # Verify the query was called with all distinct_ids
        mock_sync_execute.assert_called_once()
        call_args = mock_sync_execute.call_args
        self.assertEqual(call_args[0][1]["distinct_ids"], ["user123", "user456", "user789"])
