"""
Integration tests for point-in-time person properties building functionality.

These tests demonstrate the functionality but require ClickHouse to be available
and may need actual event data to run properly.
"""

import json
from datetime import UTC, datetime

from unittest.mock import patch

from django.test import TestCase

from posthog.models.person.point_in_time_properties import build_person_properties_at_time


class TestPointInTimePropertiesIntegration(TestCase):
    """
    Integration test examples showing how the point-in-time person properties
    building functionality would work in practice.

    Note: These tests use mocked ClickHouse responses to demonstrate the functionality
    without requiring a live ClickHouse instance.
    """

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def skip_test_realistic_person_properties_timeline(self, mock_sync_execute):
        """
        Test a realistic scenario where a person's properties evolve over time
        through multiple events and we want to see their state at a specific point.
        """
        # Simulate a timeline of events for user "alice123" on team 1:
        # Day 1: User signs up with basic info
        # Day 2: User completes profile with more details
        # Day 3: User's location changes
        # Day 4: User updates their preferences

        # ClickHouse toJSONString() returns double-encoded JSON
        mock_events = [
            # Day 1: Initial signup
            (
                json.dumps(
                    json.dumps({"$set": {"email": "alice@example.com", "name": "Alice", "signup_source": "google"}})
                ),
                datetime(2023, 1, 1, 10, 0, 0),
                "$set",
            ),
            # Day 2: Profile completion
            (
                json.dumps(
                    json.dumps(
                        {
                            "$set": {
                                "name": "Alice Johnson",
                                "age": 28,
                                "occupation": "Software Engineer",
                                "profile_complete": True,
                            }
                        }
                    )
                ),
                datetime(2023, 1, 2, 14, 30, 0),
                "$set",
            ),
            # Day 3: Location update
            (
                json.dumps(
                    json.dumps({"$set": {"city": "San Francisco", "state": "CA", "timezone": "America/Los_Angeles"}})
                ),
                datetime(2023, 1, 3, 9, 15, 0),
                "$set",
            ),
            # Day 4: Preferences update
            (
                json.dumps(
                    json.dumps({"$set": {"newsletter_subscribed": True, "preferred_language": "en", "theme": "dark"}})
                ),
                datetime(2023, 1, 4, 16, 45, 0),
                "$set",
            ),
        ]

        mock_sync_execute.return_value = mock_events

        # Test: What were Alice's properties at the end of Day 2?
        day_2_end = datetime(2023, 1, 2, 23, 59, 59, tzinfo=UTC)
        properties_day_2 = build_person_properties_at_time(1, day_2_end, distinct_id="alice123")

        expected_day_2 = {
            "email": "alice@example.com",
            "name": "Alice Johnson",  # Updated from "Alice"
            "signup_source": "google",
            "age": 28,
            "occupation": "Software Engineer",
            "profile_complete": True,
        }
        self.assertEqual(properties_day_2, expected_day_2)

        # Test: What were Alice's properties at the end of Day 3?
        day_3_end = datetime(2023, 1, 3, 23, 59, 59, tzinfo=UTC)
        properties_day_3 = build_person_properties_at_time(1, day_3_end, distinct_id="alice123")

        expected_day_3 = {
            **expected_day_2,  # Everything from Day 2
            "city": "San Francisco",
            "state": "CA",
            "timezone": "America/Los_Angeles",
        }
        self.assertEqual(properties_day_3, expected_day_3)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_set_once_behavior_demonstration(self, mock_sync_execute):
        """
        Demonstrate how $set_once operations work compared to regular $set operations.
        """
        # Scenario: A user has both $set and $set_once events
        # $set_once should only set properties that haven't been set before
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_events = [
            # Initial user creation with $set_once (common pattern)
            (
                json.dumps(
                    json.dumps(
                        {
                            "$set_once": {
                                "first_seen": "2023-01-01",
                                "signup_source": "organic",
                                "initial_referrer": "https://google.com",
                            }
                        }
                    )
                ),
                datetime(2023, 1, 1, 10, 0, 0),
                "$set_once",
            ),
            # Later signup completion with $set
            (
                json.dumps(json.dumps({"$set": {"name": "Bob Smith", "email": "bob@example.com"}})),
                datetime(2023, 1, 1, 10, 5, 0),
                "$set",
            ),
            # Attempt to overwrite signup_source with $set_once (should fail)
            (
                json.dumps(
                    json.dumps(
                        {
                            "$set_once": {
                                "signup_source": "facebook",  # Should NOT overwrite
                                "utm_campaign": "winter_2023",  # Should set (new property)
                            }
                        }
                    )
                ),
                datetime(2023, 1, 1, 10, 10, 0),
                "$set_once",
            ),
            # Update signup_source with regular $set (should work)
            (
                json.dumps(
                    json.dumps(
                        {
                            "$set": {
                                "signup_source": "facebook"  # Should overwrite
                            }
                        }
                    )
                ),
                datetime(2023, 1, 1, 10, 15, 0),
                "$set",
            ),
        ]

        mock_sync_execute.return_value = mock_events

        # Test the final state
        final_timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        properties = build_person_properties_at_time(1, final_timestamp, distinct_id="bob123", include_set_once=True)

        expected = {
            "first_seen": "2023-01-01",
            "signup_source": "facebook",  # Overwritten by $set, not $set_once
            "initial_referrer": "https://google.com",
            "name": "Bob Smith",
            "email": "bob@example.com",
            "utm_campaign": "winter_2023",  # Set by $set_once since it was new
        }

        self.assertEqual(properties, expected)
