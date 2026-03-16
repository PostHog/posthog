"""
Tests for signal handlers in posthog/models/remote_config.py.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.remote_config import (
    organization_membership_deleted,
    organization_membership_saved,
    personal_api_key_deleted,
    personal_api_key_saved,
    user_saved,
)
from posthog.models.user import User


class TestUserSavedSignalHandler(TestCase):
    """Test the user_saved signal handler in remote_config.py."""

    @parameterized.expand(
        [
            # (created, is_active, original_is_active, should_schedule_update, description)
            # New user creation always triggers cache update
            (True, True, True, True, "new user created"),
            (True, False, False, True, "new inactive user created"),
            # Existing user - is_active actually changed
            (False, False, True, True, "user deactivated"),
            (False, True, False, True, "user reactivated"),
            # Existing user - is_active unchanged (should NOT trigger)
            (False, True, True, False, "user saved but is_active unchanged (still active)"),
            (False, False, False, False, "user saved but is_active unchanged (still inactive)"),
        ]
    )
    @patch("django.db.transaction.on_commit")
    def test_user_saved_is_active_change_detection(
        self, created, is_active, original_is_active, should_schedule_update, description, mock_on_commit
    ):
        """Test user_saved signal handler detects actual is_active changes via _original_is_active."""

        # Create mock user with _original_is_active tracking
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = is_active
        mock_user._original_is_active = original_is_active

        # Call user_saved
        user_saved(sender=User, instance=mock_user, created=created)

        # Verify transaction.on_commit behavior
        if should_schedule_update:
            mock_on_commit.assert_called_once()
        else:
            mock_on_commit.assert_not_called()

    @patch("posthog.models.remote_config.logger")
    @patch("django.db.transaction.on_commit")
    def test_user_saved_logs_debug_when_skipping_update(self, mock_on_commit, mock_logger):
        """Test that user_saved logs debug message when skipping cache update."""

        # Create mock user with is_active unchanged
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True
        mock_user._original_is_active = True  # Same as current, so no change

        # Call user_saved
        user_saved(sender=User, instance=mock_user, created=False)

        # Verify debug message was logged
        mock_logger.debug.assert_called_once_with(
            "User saved but is_active unchanged, skipping cache update", user_id=42
        )

        # Verify transaction.on_commit was not called
        mock_on_commit.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_sync")
    @patch("django.db.transaction.on_commit")
    def test_user_deactivated_uses_sync_invalidation(self, mock_on_commit, mock_sync_func):
        """Test that user deactivation uses SYNC invalidation for immediate revocation (security-critical)."""

        # Create mock user with is_active change (deactivation: True -> False)
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = False
        mock_user._original_is_active = True  # Changed from True to False (deactivation)

        # Call user_saved
        user_saved(sender=User, instance=mock_user, created=False)

        # Verify transaction.on_commit was called
        mock_on_commit.assert_called_once()

        # Get the lambda function that was passed to on_commit and call it
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        # Verify that the SYNC function was called (not the Celery task)
        mock_sync_func.assert_called_once_with(42)

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_task")
    @patch("django.db.transaction.on_commit")
    def test_user_activated_uses_async_invalidation(self, mock_on_commit, mock_task):
        """Test that user activation uses ASYNC invalidation via Celery (no security concern)."""

        # Create mock user with is_active change (activation: False -> True)
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True
        mock_user._original_is_active = False  # Changed from False to True (activation)

        # Call user_saved
        user_saved(sender=User, instance=mock_user, created=False)

        # Verify transaction.on_commit was called
        mock_on_commit.assert_called_once()

        # Get the lambda function that was passed to on_commit and call it
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        # Verify that the Celery task was enqueued (async is fine for activation)
        mock_task.delay.assert_called_once_with(42)

    @patch("django.db.transaction.on_commit")
    def test_user_saved_updates_snapshot_to_prevent_double_fires(self, mock_on_commit):
        """Test that user_saved updates _original_is_active to prevent repeated cache updates on subsequent saves."""

        # Create mock user with is_active change (deactivation)
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = False
        mock_user._original_is_active = True  # Changed from True to False

        # First save - should trigger cache update
        user_saved(sender=User, instance=mock_user, created=False)
        self.assertEqual(mock_on_commit.call_count, 1)

        # Verify the snapshot was updated to current value
        self.assertEqual(mock_user._original_is_active, False)

        # Second save of same instance - should NOT trigger cache update
        user_saved(sender=User, instance=mock_user, created=False)
        self.assertEqual(mock_on_commit.call_count, 1)  # Still 1, not 2


class TestOrganizationMembershipDeletedSignalHandler(TestCase):
    """Test the organization_membership_deleted signal handler in remote_config.py."""

    @patch("django.db.transaction.on_commit")
    def test_organization_membership_deleted_calls_update_when_user_removed(self, mock_on_commit):
        """Test that organization_membership_deleted schedules cache update when a user is removed from org."""

        # Create mock OrganizationMembership
        mock_membership = MagicMock()
        mock_membership.organization_id = "test-org-uuid"
        mock_membership.user_id = 42

        # Call organization_membership_deleted
        organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)

        # Verify transaction.on_commit was called (update was scheduled)
        mock_on_commit.assert_called_once()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_task")
    @patch("django.db.transaction.on_commit")
    def test_organization_membership_deleted_uses_transaction_on_commit(self, mock_on_commit, mock_task):
        """Test that organization_membership_deleted uses transaction.on_commit to enqueue Celery task."""

        # Create mock OrganizationMembership
        mock_membership = MagicMock()
        mock_membership.organization_id = "test-org-uuid"
        mock_membership.user_id = 42

        # Call organization_membership_deleted
        organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)

        # Verify transaction.on_commit was called
        mock_on_commit.assert_called_once()

        # Get the lambda function that was passed to on_commit and call it
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        # Verify that the Celery task would be enqueued after transaction commits
        mock_task.delay.assert_called_once_with(42)

    @patch("django.db.transaction.on_commit")
    def test_organization_membership_deleted_handles_none_user(self, mock_on_commit):
        """Test that organization_membership_deleted handles membership with None user gracefully."""

        # Create mock OrganizationMembership with None user_id
        mock_membership = MagicMock()
        mock_membership.organization_id = "test-org-uuid"
        mock_membership.user_id = None

        # Should not raise an exception
        try:
            organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)
        except Exception as e:
            self.fail(f"organization_membership_deleted raised an exception with None user: {e}")

        # Should skip scheduling when user_id is None
        mock_on_commit.assert_not_called()


class TestPersonalApiKeySavedSignalHandler(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_personal_api_key_cache_task")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_on_save(self, mock_on_commit, mock_task):
        instance = MagicMock(secure_value="sha256$abc123", user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_task.delay.assert_called_once_with("sha256$abc123", 42)

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_personal_api_key_cache_task")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_on_create(self, mock_on_commit, mock_task):
        instance = MagicMock(secure_value="sha256$new_key", user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=True)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_task.delay.assert_called_once_with("sha256$new_key", 42)

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_personal_api_key_cache_task")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_for_old_and_new_value_when_key_rolled(self, mock_on_commit, mock_task):
        instance = MagicMock(secure_value="sha256$new_value", user_id=42)
        instance._old_secure_value = "sha256$old_value"
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        assert mock_on_commit.call_count == 2
        for call in mock_on_commit.call_args_list:
            call[0][0]()

        mock_task.delay.assert_any_call("sha256$new_value", 42)
        mock_task.delay.assert_any_call("sha256$old_value", 42)

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_personal_api_key_cache_task")
    @patch("django.db.transaction.on_commit")
    def test_skips_old_value_invalidation_when_unchanged(self, mock_on_commit, mock_task):
        instance = MagicMock(secure_value="sha256$same_value", user_id=42)
        instance._old_secure_value = "sha256$same_value"
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        # Only one on_commit call (for current value), not two (no old value invalidation)
        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_task.delay.assert_called_once_with("sha256$same_value", 42)

    @parameterized.expand(
        [
            (["last_used_at"], False),
            (["last_used_at", "secure_value"], True),
        ]
    )
    @patch("django.db.transaction.on_commit")
    def test_update_fields_last_used_at_guard(self, update_fields, should_schedule, mock_on_commit):
        instance = MagicMock(secure_value="sha256$abc123", user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False, update_fields=update_fields)

        if should_schedule:
            mock_on_commit.assert_called_once()
        else:
            mock_on_commit.assert_not_called()

    @patch("django.db.transaction.on_commit")
    def test_skips_when_no_secure_value(self, mock_on_commit):
        instance = MagicMock(secure_value=None, user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        mock_on_commit.assert_not_called()

    @patch("posthog.models.remote_config.capture_exception")
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_personal_api_key_cache_task")
    @patch("django.db.transaction.on_commit")
    def test_captures_exception_on_task_failure(self, mock_on_commit, mock_task, mock_capture):
        mock_task.delay.side_effect = Exception("Redis down")
        instance = MagicMock(secure_value="sha256$abc123", user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        mock_on_commit.assert_called_once()
        on_commit_callback = mock_on_commit.call_args[0][0]
        on_commit_callback()  # should not raise

        mock_capture.assert_called_once()


class TestPersonalApiKeyDeletedSignalHandler(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_personal_api_key_cache_task")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_on_delete(self, mock_on_commit, mock_task):
        instance = MagicMock(secure_value="sha256$abc123", user_id=42)
        personal_api_key_deleted(sender=PersonalAPIKey, instance=instance)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_task.delay.assert_called_once_with("sha256$abc123", 42)

    @patch("django.db.transaction.on_commit")
    def test_skips_when_no_secure_value(self, mock_on_commit):
        instance = MagicMock(secure_value=None, user_id=42)
        personal_api_key_deleted(sender=PersonalAPIKey, instance=instance)

        mock_on_commit.assert_not_called()


class TestOrganizationMembershipSavedSignalHandler(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_task")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_on_create(self, mock_on_commit, mock_task):
        instance = MagicMock(user_id=42)
        organization_membership_saved(sender=OrganizationMembership, instance=instance, created=True)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_task.delay.assert_called_once_with(42)

    @patch("django.db.transaction.on_commit")
    def test_skips_on_update(self, mock_on_commit):
        instance = MagicMock(user_id=42)
        organization_membership_saved(sender=OrganizationMembership, instance=instance, created=False)

        mock_on_commit.assert_not_called()

    @patch("django.db.transaction.on_commit")
    def test_skips_when_user_id_is_none(self, mock_on_commit):
        instance = MagicMock(user_id=None)
        organization_membership_saved(sender=OrganizationMembership, instance=instance, created=True)

        mock_on_commit.assert_not_called()
