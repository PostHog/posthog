"""
Tests for signal handlers in posthog/models/remote_config.py.
"""

from unittest.mock import patch, MagicMock
from django.test import TestCase

from posthog.models.user import User
from posthog.models.remote_config import user_saved


class TestUserSavedSignalHandler(TestCase):
    """Test the user_saved signal handler in remote_config.py."""

    @patch("django.db.transaction.on_commit")
    def test_user_saved_calls_update_when_is_active_in_update_fields(self, mock_on_commit):
        """Test that user_saved schedules update_user_authentication_cache when is_active is in update_fields."""

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Call user_saved with is_active in update_fields
        user_saved(sender=User, instance=mock_user, created=False, update_fields=["is_active", "email"])

        # Verify transaction.on_commit was called (update was scheduled)
        mock_on_commit.assert_called_once()

    @patch("django.db.transaction.on_commit")
    def test_user_saved_calls_update_when_update_fields_is_none(self, mock_on_commit):
        """Test that user_saved schedules update_user_authentication_cache when update_fields is None (bulk operations)."""

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = False

        # Call user_saved without update_fields (None means bulk operation)
        user_saved(sender=User, instance=mock_user, created=False, update_fields=None)

        # Verify transaction.on_commit was called (update was scheduled)
        mock_on_commit.assert_called_once()

    @patch("django.db.transaction.on_commit")
    def test_user_saved_does_not_call_update_when_is_active_not_in_update_fields(self, mock_on_commit):
        """Test that user_saved does not schedule update when is_active is not in update_fields."""
        from posthog.models.remote_config import user_saved

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Call user_saved with is_active NOT in update_fields
        user_saved(sender=User, instance=mock_user, created=False, update_fields=["email", "name"])

        # Verify transaction.on_commit was NOT called (update was not scheduled)
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

    @patch("django.db.transaction.on_commit")
    def test_user_saved_handles_empty_update_fields_list(self, mock_on_commit):
        """Test that user_saved handles empty update_fields list correctly."""

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Call user_saved with empty update_fields list
        user_saved(sender=User, instance=mock_user, created=False, update_fields=[])

        # Verify transaction.on_commit was NOT called (is_active not in empty list)
        mock_on_commit.assert_not_called()

    @patch("django.db.transaction.on_commit")
    def test_user_saved_handles_is_active_as_only_field(self, mock_on_commit):
        """Test that user_saved works when is_active is the only field in update_fields."""

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = False

        # Call user_saved with only is_active in update_fields
        user_saved(sender=User, instance=mock_user, created=False, update_fields=["is_active"])

        # Verify transaction.on_commit was called (update was scheduled)
        mock_on_commit.assert_called_once()
