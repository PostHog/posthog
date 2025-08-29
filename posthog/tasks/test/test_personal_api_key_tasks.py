"""
Unit tests for personal API key usage tracking tasks.
"""

import uuid
from datetime import UTC, timedelta
from typing import Any

from freezegun import freeze_time
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from posthog.models import Organization, PersonalAPIKey, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.tasks.personal_api_key_tasks import (
    schedule_personal_api_key_usage_update,
    update_personal_api_key_last_used,
)


class TestUpdatePersonalAPIKeyLastUsed(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Organization")
        self.user = User.objects.create(
            email="test@example.com",
            is_active=True,
        )
        # Generate a token for the personal API key
        self.token_value = generate_random_token_personal()
        self.personal_api_key = PersonalAPIKey.objects.create(
            id=str(uuid.uuid4()),
            user=self.user,
            label="Test Key",
            secure_value=hash_key_value(self.token_value),
            mask_value=mask_key_value(self.token_value),
        )

    def test_successful_update_when_no_previous_usage(self) -> None:
        """Test updating last_used_at when key has never been used."""
        # Ensure the key has no previous usage
        self.personal_api_key.last_used_at = None
        self.personal_api_key.save()

        timestamp = timezone.now()
        timestamp_iso = timestamp.isoformat()

        # Execute the task
        update_personal_api_key_last_used(self.personal_api_key.id, timestamp_iso)

        # Verify the update
        self.personal_api_key.refresh_from_db()
        self.assertIsNotNone(self.personal_api_key.last_used_at)
        self.assertEqual(self.personal_api_key.last_used_at, timestamp)

    def test_successful_update_when_more_than_hour_passed(self) -> None:
        """Test updating last_used_at when more than 1 hour has passed."""
        # Set last usage to 2 hours ago
        old_timestamp = timezone.now() - timedelta(hours=2)
        self.personal_api_key.last_used_at = old_timestamp
        self.personal_api_key.save()

        new_timestamp = timezone.now()
        timestamp_iso = new_timestamp.isoformat()

        # Execute the task
        update_personal_api_key_last_used(self.personal_api_key.id, timestamp_iso)

        # Verify the update
        self.personal_api_key.refresh_from_db()
        self.assertEqual(self.personal_api_key.last_used_at, new_timestamp)

    def test_no_update_when_less_than_hour_passed(self) -> None:
        """Test no update when less than 1 hour has passed."""
        # Set last usage to 30 minutes ago
        old_timestamp = timezone.now() - timedelta(minutes=30)
        self.personal_api_key.last_used_at = old_timestamp
        self.personal_api_key.save()

        new_timestamp = timezone.now()
        timestamp_iso = new_timestamp.isoformat()

        # Execute the task
        update_personal_api_key_last_used(self.personal_api_key.id, timestamp_iso)

        # Verify no update occurred
        self.personal_api_key.refresh_from_db()
        self.assertEqual(self.personal_api_key.last_used_at, old_timestamp)

    def test_key_not_found_handles_gracefully(self) -> None:
        """Test that missing keys are handled gracefully."""
        nonexistent_key_id = str(uuid.uuid4())
        timestamp_iso = timezone.now().isoformat()

        # Execute the task - should not raise exception
        update_personal_api_key_last_used(nonexistent_key_id, timestamp_iso)

        # Verify original key is unchanged
        self.personal_api_key.refresh_from_db()

    def test_invalid_timestamp_handles_gracefully(self) -> None:
        """Test that invalid timestamps are handled gracefully."""
        invalid_timestamp = "not-a-timestamp"

        # Execute the task - should not raise exception
        update_personal_api_key_last_used(self.personal_api_key.id, invalid_timestamp)

        # Verify original key is unchanged
        self.personal_api_key.refresh_from_db()

    @patch("posthog.tasks.personal_api_key_tasks.logger")
    def test_database_error_logs_and_continues(self, mock_logger: Any) -> None:
        """Test that database errors are logged but don't raise exceptions."""
        # Mock a database error on the get() call
        with patch("posthog.models.personal_api_key.PersonalAPIKey.objects.select_for_update") as mock_select:
            from django.db import OperationalError

            mock_select.return_value.get.side_effect = OperationalError("Database connection lost")

            timestamp_iso = timezone.now().isoformat()

            # Execute the task - should not raise exception
            update_personal_api_key_last_used(self.personal_api_key.id, timestamp_iso)

            # Verify error was logged
            mock_logger.warning.assert_called()

    def test_timezone_aware_timestamps(self) -> None:
        """Test that timezone-aware timestamps are handled correctly."""
        # Test with UTC timestamp
        timestamp = timezone.now().replace(tzinfo=UTC)
        timestamp_iso = timestamp.isoformat()

        update_personal_api_key_last_used(self.personal_api_key.id, timestamp_iso)

        self.personal_api_key.refresh_from_db()
        self.assertEqual(self.personal_api_key.last_used_at, timestamp)


class TestSchedulePersonalAPIKeyUsageUpdate(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Organization")
        self.user = User.objects.create(
            email="test@example.com",
            is_active=True,
        )
        self.token_value = generate_random_token_personal()
        self.personal_api_key = PersonalAPIKey.objects.create(
            id=str(uuid.uuid4()),
            user=self.user,
            label="Test Key",
            secure_value=hash_key_value(self.token_value),
            mask_value=mask_key_value(self.token_value),
        )

    @patch("posthog.tasks.personal_api_key_tasks.update_personal_api_key_last_used.delay")
    def test_successful_scheduling(self, mock_delay: Any) -> None:
        """Test successful task scheduling."""
        timestamp = timezone.now()

        result = schedule_personal_api_key_usage_update(self.personal_api_key.id, timestamp)

        self.assertTrue(result)
        mock_delay.assert_called_once()

        # Verify the call arguments
        call_args = mock_delay.call_args[0]
        self.assertEqual(call_args[0], self.personal_api_key.id)
        self.assertEqual(call_args[1], timestamp.isoformat())

    @patch("posthog.tasks.personal_api_key_tasks.update_personal_api_key_last_used.delay")
    def test_scheduling_with_default_timestamp(self, mock_delay: Any) -> None:
        """Test scheduling with default timestamp (now)."""
        with freeze_time("2023-01-01T12:00:00Z"):
            result = schedule_personal_api_key_usage_update(self.personal_api_key.id)

            self.assertTrue(result)
            mock_delay.assert_called_once()

            # Verify timestamp was set to current time (with timezone info)
            call_args = mock_delay.call_args[0]
            self.assertEqual(call_args[1], "2023-01-01T12:00:00+00:00")

    @patch("posthog.tasks.personal_api_key_tasks.update_personal_api_key_last_used.delay")
    @patch("posthog.tasks.personal_api_key_tasks.logger")
    def test_scheduling_failure_logs_and_returns_false(self, mock_logger: Any, mock_delay: Any) -> None:
        """Test that scheduling failures are logged and return False."""
        # Mock task scheduling failure
        mock_delay.side_effect = Exception("Celery broker unavailable")

        result = schedule_personal_api_key_usage_update(self.personal_api_key.id)

        self.assertFalse(result)
        mock_logger.warning.assert_called()

    @patch("posthog.tasks.personal_api_key_tasks.update_personal_api_key_last_used.delay")
    def test_scheduling_with_custom_timestamp(self, mock_delay: Any) -> None:
        """Test scheduling with a custom timestamp."""
        custom_timestamp = timezone.now() - timedelta(minutes=5)

        result = schedule_personal_api_key_usage_update(self.personal_api_key.id, custom_timestamp)

        self.assertTrue(result)
        call_args = mock_delay.call_args[0]
        self.assertEqual(call_args[1], custom_timestamp.isoformat())
