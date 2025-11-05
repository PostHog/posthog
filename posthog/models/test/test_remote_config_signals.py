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
            # (update_fields, should_schedule_update, description)
            (["is_active", "email"], True, "is_active in update_fields"),
            (None, True, "update_fields is None (bulk operation)"),
            (["email", "name"], False, "is_active not in update_fields"),
            ([], False, "empty update_fields list"),
            (["is_active"], True, "only is_active in update_fields"),
        ]
    )
    @patch("django.db.transaction.on_commit")
    def test_user_saved_update_fields_scenarios(
        self, update_fields, should_schedule_update, description, mock_on_commit
    ):
        """Test user_saved signal handler for various update_fields scenarios."""

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Call user_saved with specified update_fields
        user_saved(sender=User, instance=mock_user, created=False, update_fields=update_fields)

        # Verify transaction.on_commit behavior
        if should_schedule_update:
            mock_on_commit.assert_called_once()
        else:
            mock_on_commit.assert_not_called()

    @patch("posthog.models.remote_config.logger")
    @patch("django.db.transaction.on_commit")
    def test_user_saved_logs_debug_when_skipping_update(self, mock_on_commit, mock_logger):
        """Test that user_saved logs debug message when skipping cache update."""

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Call user_saved with is_active NOT in update_fields
        user_saved(sender=User, instance=mock_user, created=False, update_fields=["email", "name"])

        # Verify debug message was logged
        mock_logger.debug.assert_called_once_with("User 42 updated but is_active unchanged, skipping cache update")

        # Verify transaction.on_commit was not called
        mock_on_commit.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.update_user_authentication_cache")
    @patch("django.db.transaction.on_commit")
    def test_user_saved_uses_transaction_on_commit(self, mock_on_commit, mock_update_cache):
        """Test that user_saved uses transaction.on_commit to defer cache updates."""

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Call user_saved with is_active in update_fields
        user_saved(sender=User, instance=mock_user, created=False, update_fields=["is_active"])

        # Verify transaction.on_commit was called
        mock_on_commit.assert_called_once()

        # Get the lambda function that was passed to on_commit and call it
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        # Verify that the update function would be called after transaction commits
        # The lambda passes instance and **kwargs (which doesn't include created)
        mock_update_cache.assert_called_once_with(mock_user, update_fields=["is_active"])


class TestOrganizationMembershipDeletedSignalHandler(TestCase):
    """Test the organization_membership_deleted signal handler in remote_config.py."""

    @patch("django.db.transaction.on_commit")
    def test_organization_membership_deleted_calls_update_when_user_removed(self, mock_on_commit):
        """Test that organization_membership_deleted schedules cache update when a user is removed from org."""

        # Create mock user and organization
        mock_user = MagicMock()
        mock_user.id = 42

        mock_org = MagicMock()
        mock_org.id = "test-org-uuid"

        # Create mock OrganizationMembership
        mock_membership = MagicMock()
        mock_membership.user = mock_user
        mock_membership.organization = mock_org

        # Call organization_membership_deleted
        organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)

        # Verify transaction.on_commit was called (update was scheduled)
        mock_on_commit.assert_called_once()

    @patch("posthog.storage.team_access_cache_signal_handlers.update_organization_membership_deleted_cache")
    @patch("django.db.transaction.on_commit")
    def test_organization_membership_deleted_uses_transaction_on_commit(self, mock_on_commit, mock_update_cache):
        """Test that organization_membership_deleted uses transaction.on_commit to defer cache updates."""

        # Create mock user and organization
        mock_user = MagicMock()
        mock_user.id = 42

        mock_org = MagicMock()
        mock_org.id = "test-org-uuid"

        # Create mock OrganizationMembership
        mock_membership = MagicMock()
        mock_membership.user = mock_user
        mock_membership.organization = mock_org
        mock_membership.organization_id = "test-org-uuid"
        mock_membership.user_id = 42

        # Call organization_membership_deleted
        organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)

        # Verify transaction.on_commit was called
        mock_on_commit.assert_called_once()

        # Get the lambda function that was passed to on_commit and call it
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        # Verify that the update function would be called after transaction commits
        # The lambda passes the membership instance
        mock_update_cache.assert_called_once_with(mock_membership)

    @patch("posthog.models.remote_config.logger")
    @patch("django.db.transaction.on_commit")
    def test_organization_membership_deleted_logs_when_scheduled(self, mock_on_commit, mock_logger):
        """Test that organization_membership_deleted properly schedules cache updates."""

        # Create mock user and organization
        mock_user = MagicMock()
        mock_user.id = 42

        mock_org = MagicMock()
        mock_org.id = "test-org-uuid"

        # Create mock OrganizationMembership
        mock_membership = MagicMock()
        mock_membership.user = mock_user
        mock_membership.organization = mock_org

        # Call organization_membership_deleted
        organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)

        # Verify transaction.on_commit was called (update was scheduled)
        mock_on_commit.assert_called_once()

    def test_organization_membership_deleted_handles_none_user(self):
        """Test that organization_membership_deleted handles membership with None user gracefully."""

        # Create mock OrganizationMembership with None user
        mock_membership = MagicMock()
        mock_membership.user = None

        # Should not raise an exception
        try:
            organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)
        except Exception as e:
            self.fail(f"organization_membership_deleted raised an exception with None user: {e}")

    @patch("django.db.transaction.on_commit")
    def test_organization_membership_deleted_with_different_kwargs(self, mock_on_commit):
        """Test that organization_membership_deleted properly forwards kwargs to the cache update."""

        # Create mock user and organization
        mock_user = MagicMock()
        mock_user.id = 42

        mock_org = MagicMock()
        mock_org.id = "test-org-uuid"

        # Create mock OrganizationMembership
        mock_membership = MagicMock()
        mock_membership.user = mock_user
        mock_membership.organization = mock_org

        # Call organization_membership_deleted with additional kwargs
        test_kwargs = {"raw": False, "using": "default"}
        organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership, **test_kwargs)

        # Verify transaction.on_commit was called
        mock_on_commit.assert_called_once()
