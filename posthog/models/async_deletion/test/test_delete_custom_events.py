from unittest.mock import patch

from posthog.models.async_deletion.async_deletion import AsyncDeletion, DeletionType
from posthog.models.async_deletion.delete_custom_events import AsyncCustomEventDeletion
from posthog.models.team import Team
from posthog.models.organization import Organization
from posthog.test.base import BaseTest


class TestAsyncCustomEventDeletion(BaseTest):
    """Test the AsyncCustomEventDeletion process class."""

    def setUp(self):
        super().setUp()
        self.deletion_process = AsyncCustomEventDeletion()

    def test_deletion_types(self):
        """Test that only Custom deletion type is supported."""
        self.assertEqual(self.deletion_process.DELETION_TYPES, [DeletionType.Custom])

    def test_process_no_deletions(self):
        """Test process method with empty deletion list."""
        with patch("posthog.models.async_deletion.delete_custom_events.logger") as mock_logger:
            self.deletion_process.process([])
            mock_logger.debug.assert_called_once_with("No AsyncDeletion to perform")

    @patch("posthog.models.async_deletion.delete_custom_events.sync_execute")
    def test_process_single_deletion(self, mock_sync_execute):
        """Test processing a single custom deletion."""
        # Create a custom deletion
        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom,
            team_id=self.team.id,
            key="properties.$geoip_disable = 1",
            created_by=self.user,
        )

        self.deletion_process.process([deletion])

        # Verify sync_execute was called with correct query
        mock_sync_execute.assert_called_once()
        call_args = mock_sync_execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        # Check query structure
        self.assertIn("DELETE FROM sharded_events", query)
        self.assertIn("WHERE team_id = %(team_id)s", query)
        self.assertIn("properties.$geoip_disable = 1", query)

        # Check parameters
        self.assertEqual(params["team_id"], self.team.id)

    @patch("posthog.models.async_deletion.delete_custom_events.sync_execute")
    def test_process_multiple_deletions(self, mock_sync_execute):
        """Test processing multiple custom deletions."""
        # Create multiple custom deletions for different teams
        org2 = Organization.objects.create(name="Org 2")
        team2 = Team.objects.create(organization=org2, name="Team 2")

        deletion1 = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key='event = "test_event"', created_by=self.user
        )

        deletion2 = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=team2.id, key="properties.error = 1", created_by=self.user
        )

        self.deletion_process.process([deletion1, deletion2])

        # Verify sync_execute was called twice (once per deletion)
        self.assertEqual(mock_sync_execute.call_count, 2)

        # Verify each call had correct team_id
        calls = mock_sync_execute.call_args_list
        team_ids_called = [call[0][1]["team_id"] for call in calls]
        self.assertIn(self.team.id, team_ids_called)
        self.assertIn(team2.id, team_ids_called)

    @patch("posthog.models.async_deletion.delete_custom_events.sync_execute")
    @patch("posthog.models.async_deletion.delete_custom_events.logger")
    def test_process_socket_timeout_error(self, mock_logger, mock_sync_execute):
        """Test handling of SocketTimeoutError during deletion."""
        from clickhouse_driver.errors import SocketTimeoutError

        mock_sync_execute.side_effect = SocketTimeoutError("Connection timeout")

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.test = 1", created_by=self.user
        )

        # Should not raise exception
        self.deletion_process.process([deletion])

        # Should log warning
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        self.assertIn("timed out", warning_call)
        self.assertIn(str(self.team.id), warning_call)

    @patch("posthog.models.async_deletion.delete_custom_events.sync_execute")
    @patch("posthog.models.async_deletion.delete_custom_events.logger")
    def test_process_general_error(self, mock_logger, mock_sync_execute):
        """Test handling of general errors during deletion."""
        mock_sync_execute.side_effect = Exception("Database error")

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.test = 1", created_by=self.user
        )

        # Should not raise exception
        self.deletion_process.process([deletion])

        # Should log error
        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        self.assertIn("Error executing custom deletion", error_call)
        self.assertIn(str(self.team.id), error_call)

    @patch("posthog.models.async_deletion.delete_custom_events.sync_execute")
    def test_verify_by_group_non_custom_type(self, mock_sync_execute):
        """Test _verify_by_group returns empty list for non-Custom deletion types."""
        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Team, team_id=self.team.id, key=str(self.team.id), created_by=self.user
        )

        result = self.deletion_process._verify_by_group(DeletionType.Team, [deletion])
        self.assertEqual(result, [])
        mock_sync_execute.assert_not_called()

    @patch("posthog.models.async_deletion.delete_custom_events.sync_execute")
    def test_verify_by_group_deletion_complete(self, mock_sync_execute):
        """Test _verify_by_group when deletion is complete (no matching events)."""
        mock_sync_execute.return_value = [[0]]  # No events found

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.deleted = 1", created_by=self.user
        )

        result = self.deletion_process._verify_by_group(DeletionType.Custom, [deletion])

        # Should return the deletion as verified
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], deletion)

        # Verify query was called correctly
        mock_sync_execute.assert_called_once()
        call_args = mock_sync_execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        self.assertIn("SELECT count()", query)
        self.assertIn("WHERE team_id = %(team_id)s", query)
        self.assertIn("properties.deleted = 1", query)
        self.assertEqual(params["team_id"], self.team.id)

    @patch("posthog.models.async_deletion.delete_custom_events.sync_execute")
    def test_verify_by_group_deletion_incomplete(self, mock_sync_execute):
        """Test _verify_by_group when deletion is incomplete (events still exist)."""
        mock_sync_execute.return_value = [[5]]  # 5 events still exist

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.pending = 1", created_by=self.user
        )

        result = self.deletion_process._verify_by_group(DeletionType.Custom, [deletion])

        # Should return empty list (not verified)
        self.assertEqual(result, [])

    @patch("posthog.models.async_deletion.delete_custom_events.sync_execute")
    @patch("posthog.models.async_deletion.delete_custom_events.logger")
    def test_verify_by_group_query_error(self, mock_logger, mock_sync_execute):
        """Test _verify_by_group handles query errors gracefully."""
        mock_sync_execute.side_effect = Exception("Query failed")

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.test = 1", created_by=self.user
        )

        result = self.deletion_process._verify_by_group(DeletionType.Custom, [deletion])

        # Should return empty list and log error
        self.assertEqual(result, [])
        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        self.assertIn("Error verifying custom deletion", error_call)

    def test_condition_method(self):
        """Test _condition method returns correct SQL condition."""
        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom,
            team_id=self.team.id,
            key='properties.custom = "value"',
            created_by=self.user,
        )

        condition, params = self.deletion_process._condition(deletion, "123")

        expected_condition = f"(team_id = %(team_id123)s AND ({deletion.key}))"
        self.assertEqual(condition, expected_condition)
        self.assertEqual(params, {f"team_id123": self.team.id})

    @patch("posthog.models.async_deletion.delete_custom_events.sync_execute")
    def test_verify_multiple_deletions(self, mock_sync_execute):
        """Test verification of multiple deletions with mixed results."""
        # First deletion complete, second incomplete
        mock_sync_execute.side_effect = [[0], [3]]

        deletion1 = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.complete = 1", created_by=self.user
        )

        deletion2 = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom,
            team_id=self.team.id,
            key="properties.incomplete = 1",
            created_by=self.user,
        )

        result = self.deletion_process._verify_by_group(DeletionType.Custom, [deletion1, deletion2])

        # Should return only the completed deletion
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], deletion1)

        # Should have called sync_execute twice
        self.assertEqual(mock_sync_execute.call_count, 2)

    def test_team_id_validation_in_queries(self):
        """Test that team_id is always included in deletion queries."""
        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key='event = "test"', created_by=self.user
        )

        with patch("posthog.models.async_deletion.delete_custom_events.sync_execute") as mock_sync_execute:
            self.deletion_process.process([deletion])

            # Verify query includes team_id constraint
            call_args = mock_sync_execute.call_args
            query = call_args[0][0]
            params = call_args[0][1]

            # Query must include team_id filter
            self.assertIn("team_id = %(team_id)s", query)
            self.assertIn("team_id", params)
            self.assertEqual(params["team_id"], self.team.id)

            # Predicate should be wrapped in parentheses for safety
            self.assertIn('(event = "test")', query)
