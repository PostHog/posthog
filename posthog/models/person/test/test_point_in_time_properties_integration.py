"""
Integration tests for point-in-time person properties building functionality.

These tests demonstrate the functionality but require ClickHouse to be available
and may need actual event data to run properly.
"""

import json
from datetime import UTC, datetime

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.models.person.point_in_time_properties import build_person_properties_at_time


def _prop_row(set_dict: dict | None = None, set_once_dict: dict | None = None, event: str = "$set") -> tuple:
    return (
        1,
        json.dumps(set_dict) if set_dict is not None else "",
        json.dumps(set_once_dict) if set_once_dict is not None else "",
        event,
    )


def _existence_row() -> tuple:
    return (0, "", "", "")


class TestPointInTimePropertiesIntegration(SimpleTestCase):
    """
    Integration test examples showing how the point-in-time person properties
    building functionality would work in practice.

    Note: These tests use mocked ClickHouse responses to demonstrate the functionality
    without requiring a live ClickHouse instance.
    """

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_realistic_person_properties_timeline(self, mock_sync_execute):
        # Simulate a timeline of events for user "alice123" on team 1:
        # Day 1: User signs up with basic info
        # Day 2: User completes profile with more details
        # Day 3: User's location changes
        # Day 4: User updates their preferences
        timeline = [
            (
                _prop_row(set_dict={"email": "alice@example.com", "name": "Alice", "signup_source": "google"}),
                datetime(2023, 1, 1, 10, 0, 0),
            ),
            (
                _prop_row(
                    set_dict={
                        "name": "Alice Johnson",
                        "age": 28,
                        "occupation": "Software Engineer",
                        "profile_complete": True,
                    }
                ),
                datetime(2023, 1, 2, 14, 30, 0),
            ),
            (
                _prop_row(set_dict={"city": "San Francisco", "state": "CA", "timezone": "America/Los_Angeles"}),
                datetime(2023, 1, 3, 9, 15, 0),
            ),
            (
                _prop_row(set_dict={"newsletter_subscribed": True, "preferred_language": "en", "theme": "dark"}),
                datetime(2023, 1, 4, 16, 45, 0),
            ),
        ]

        def mock_query_with_timestamp_filter(query, params, settings=None):
            query_timestamp = datetime.strptime(params["upper_bound"], "%Y-%m-%d %H:%M:%S")
            filtered_rows = [row for row, ts in timeline if ts <= query_timestamp]
            if filtered_rows:
                filtered_rows.append(_existence_row())
            return filtered_rows

        mock_sync_execute.side_effect = mock_query_with_timestamp_filter

        day_2_end = datetime(2023, 1, 2, 23, 59, 59, tzinfo=UTC)
        properties_day_2, existed_day_2 = build_person_properties_at_time(1, day_2_end, ["alice123"])

        expected_day_2 = {
            "email": "alice@example.com",
            "name": "Alice Johnson",
            "signup_source": "google",
            "age": 28,
            "occupation": "Software Engineer",
            "profile_complete": True,
        }
        self.assertEqual(properties_day_2, expected_day_2)
        self.assertTrue(existed_day_2)

        day_3_end = datetime(2023, 1, 3, 23, 59, 59, tzinfo=UTC)
        properties_day_3, _ = build_person_properties_at_time(1, day_3_end, ["alice123"])

        expected_day_3 = {
            **expected_day_2,
            "city": "San Francisco",
            "state": "CA",
            "timezone": "America/Los_Angeles",
        }
        self.assertEqual(properties_day_3, expected_day_3)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_set_once_behavior_demonstration(self, mock_sync_execute):
        timeline = [
            (
                _prop_row(
                    set_once_dict={
                        "first_seen": "2023-01-01",
                        "signup_source": "organic",
                        "initial_referrer": "https://google.com",
                    },
                    event="$set_once",
                ),
                datetime(2023, 1, 1, 10, 0, 0),
            ),
            (
                _prop_row(set_dict={"name": "Bob Smith", "email": "bob@example.com"}, event="$set"),
                datetime(2023, 1, 1, 10, 5, 0),
            ),
            (
                _prop_row(
                    set_once_dict={
                        "signup_source": "facebook",  # should NOT overwrite the earlier $set_once value
                        "utm_campaign": "winter_2023",
                    },
                    event="$set_once",
                ),
                datetime(2023, 1, 1, 10, 10, 0),
            ),
            (_prop_row(set_dict={"signup_source": "facebook"}, event="$set"), datetime(2023, 1, 1, 10, 15, 0)),
        ]

        def mock_query_with_timestamp_filter_set_once(query, params, settings=None):
            query_timestamp = datetime.strptime(params["upper_bound"], "%Y-%m-%d %H:%M:%S")
            filtered_rows = [row for row, ts in timeline if ts <= query_timestamp]
            if filtered_rows:
                filtered_rows.append(_existence_row())
            return filtered_rows

        mock_sync_execute.side_effect = mock_query_with_timestamp_filter_set_once

        final_timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        properties, _ = build_person_properties_at_time(1, final_timestamp, ["bob123"], include_set_once=True)

        expected = {
            "first_seen": "2023-01-01",
            "signup_source": "facebook",  # $set overrode earlier $set_once
            "initial_referrer": "https://google.com",
            "name": "Bob Smith",
            "email": "bob@example.com",
            "utm_campaign": "winter_2023",  # set by later $set_once since it was new
        }

        self.assertEqual(properties, expected)
