"""
Tests for signal handlers in posthog/models/remote_config.py.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.models.remote_config import organization_membership_deleted, user_saved
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
        mock_logger.debug.assert_called_once_with("User 42 saved but is_active unchanged, skipping cache update")

        # Verify transaction.on_commit was not called
        mock_on_commit.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.warm_user_teams_cache_sync")
    @patch("django.db.transaction.on_commit")
    def test_user_deactivated_uses_sync_cache_update(self, mock_on_commit, mock_sync_func):
        """Test that user deactivation uses SYNC cache update for immediate revocation (security-critical)."""

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

    @patch("posthog.tasks.team_access_cache_tasks.warm_user_teams_cache_task")
    @patch("django.db.transaction.on_commit")
    def test_user_activated_uses_async_cache_update(self, mock_on_commit, mock_task):
        """Test that user activation uses ASYNC cache update via Celery (no security concern)."""

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

    @patch("posthog.tasks.team_access_cache_tasks.warm_organization_teams_cache_task")
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
        mock_task.delay.assert_called_once_with("test-org-uuid", 42, "removed from organization")

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

        # Should still schedule the task
        mock_on_commit.assert_called_once()
