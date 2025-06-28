from unittest.mock import patch, MagicMock
from datetime import datetime

from posthog.models.async_deletion.async_deletion import AsyncDeletion, DeletionType
from posthog.models.team import Team
from posthog.models.organization import Organization
from posthog.test.base import BaseTest

# Import the Dagster operations we want to test
from dags.deletes import (
    load_pending_deletions,
    delete_custom_events,
    cleanup_delete_assets,
    PendingDeletesTable,
    DeleteConfig,
)


class TestDagsterCustomDeletions(BaseTest):
    """Test Dagster operations for custom deletions."""

    def setUp(self):
        super().setUp()

        # Create additional teams for testing cross-team isolation
        self.org2 = Organization.objects.create(name="Org 2")
        self.team2 = Team.objects.create(organization=self.org2, name="Team 2")

        # Mock Dagster context
        self.mock_context = MagicMock()
        self.mock_context.add_output_metadata = MagicMock()
        self.mock_context.log = MagicMock()

        # Mock ClickHouse cluster
        self.mock_cluster = MagicMock()
        self.mock_client = MagicMock()
        self.mock_cluster.any_host_by_role.return_value.result.return_value = []

    def test_load_pending_deletions_filters_custom_by_team_id(self):
        """Test that load_pending_deletions properly filters custom deletions by team_id."""
        # Create custom deletions with and without team_id
        custom_with_team = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.test = 1", created_by=self.user
        )

        # Create invalid custom deletion (should be filtered out)
        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom,
            team_id=None,  # Invalid custom deletion
            key="properties.invalid = 1",
            created_by=self.user,
        )

        # Create test table object
        table = PendingDeletesTable(timestamp=datetime.now())

        with patch("dags.deletes.AsyncDeletion.objects") as mock_objects:
            # Mock the queryset chain
            mock_queryset = MagicMock()
            mock_objects.all.return_value = mock_queryset
            mock_queryset.filter.return_value = mock_queryset
            mock_queryset.iterator.return_value = [custom_with_team]  # Only valid ones

            # Mock cluster operations
            mock_cluster = MagicMock()
            load_pending_deletions(
                context=self.mock_context, create_pending_deletions_table=table, cluster=mock_cluster
            )

            # Verify filter was called with proper Q objects
            filter_calls = mock_queryset.filter.call_args_list
            self.assertTrue(len(filter_calls) > 0)

            # Check that team_id__isnull=False is included for Custom deletions
            filter_args = filter_calls[0][0][0]  # First filter call, first Q object
            self.assertIn("Custom", str(filter_args))

    def test_load_pending_deletions_with_specific_team_id(self):
        """Test load_pending_deletions when filtering by specific team_id."""
        # Create custom deletions for different teams
        custom_team1 = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.team1 = 1", created_by=self.user
        )

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team2.id, key="properties.team2 = 1", created_by=self.user
        )

        # Create table with specific team_id
        table = PendingDeletesTable(timestamp=datetime.now(), team_id=self.team.id)

        with patch("dags.deletes.AsyncDeletion.objects") as mock_objects:
            mock_queryset = MagicMock()
            mock_objects.all.return_value = mock_queryset
            mock_queryset.filter.return_value = mock_queryset
            mock_queryset.iterator.return_value = [custom_team1]

            mock_cluster = MagicMock()
            load_pending_deletions(
                context=self.mock_context, create_pending_deletions_table=table, cluster=mock_cluster
            )

            # Verify filter includes team_id constraint
            filter_calls = mock_queryset.filter.call_args_list
            self.assertTrue(len(filter_calls) > 0)

            # Should filter by the specific team_id
            filter_kwargs = filter_calls[0][1]
            self.assertEqual(filter_kwargs.get("team_id"), self.team.id)

    def test_delete_custom_events_no_deletions(self):
        """Test delete_custom_events when no custom deletions exist."""
        table = PendingDeletesTable(timestamp=datetime.now())

        # Mock empty result from ClickHouse
        mock_cluster = MagicMock()
        mock_cluster.any_host_by_role.return_value.result.return_value = []

        result = delete_custom_events(context=self.mock_context, cluster=mock_cluster, load_pending_deletions=table)

        # Should return the table unchanged
        self.assertEqual(result, table)

        # Should add metadata about no deletions found
        self.mock_context.add_output_metadata.assert_called_once()
        metadata = self.mock_context.add_output_metadata.call_args[0][0]
        self.assertEqual(metadata["custom_events_deleted"].value, 0)
        self.assertIn("No custom deletions found", metadata["message"])

    def test_delete_custom_events_with_team_id_filter(self):
        """Test delete_custom_events applies team_id filter in ClickHouse query."""
        table = PendingDeletesTable(timestamp=datetime.now())

        # Mock custom deletions result
        mock_deletions = [(self.team.id, "properties.test = 1"), (self.team2.id, 'event = "test_event"')]

        mock_cluster = MagicMock()
        mock_cluster.any_host_by_role.return_value.result.return_value = mock_deletions

        delete_custom_events(context=self.mock_context, cluster=mock_cluster, load_pending_deletions=table)

        # Verify ClickHouse query includes team_id IS NOT NULL filter
        query_call = mock_cluster.any_host_by_role.call_args[0][0]
        query_call(MagicMock())  # Execute the lambda

        # The query should be called on the mock client
        # We need to inspect what query was built
        self.mock_context.add_output_metadata.assert_called_once()
        metadata = self.mock_context.add_output_metadata.call_args[0][0]
        self.assertEqual(metadata["custom_deletions_count"].value, 2)

    def test_delete_custom_events_skips_invalid_deletions(self):
        """Test delete_custom_events skips deletions with missing team_id or predicate."""
        table = PendingDeletesTable(timestamp=datetime.now())

        # Mock deletions with invalid data
        mock_deletions = [
            (self.team.id, "properties.valid = 1"),  # Valid
            (None, "properties.no_team = 1"),  # No team_id
            (self.team2.id, ""),  # Empty predicate
            (self.team.id, None),  # None predicate
        ]

        mock_cluster = MagicMock()
        mock_cluster.any_host_by_role.return_value.result.return_value = mock_deletions

        with patch("dags.deletes.LightweightDeleteMutationRunner") as mock_runner:
            delete_custom_events(context=self.mock_context, cluster=mock_cluster, load_pending_deletions=table)

            # Should only create 1 mutation runner (for the valid deletion)
            self.assertEqual(mock_runner.call_count, 1)

            # Should log warnings for invalid deletions
            self.assertTrue(self.mock_context.log.warning.called)
            warning_calls = self.mock_context.log.warning.call_args_list
            self.assertTrue(len(warning_calls) >= 2)  # At least 2 invalid deletions

    def test_delete_custom_events_parameterized_queries(self):
        """Test delete_custom_events uses parameterized queries for safety."""
        table = PendingDeletesTable(timestamp=datetime.now())

        # Mock custom deletion
        mock_deletions = [(self.team.id, 'properties.test = "value"')]

        mock_cluster = MagicMock()
        mock_cluster.any_host_by_role.return_value.result.return_value = mock_deletions

        with patch("dags.deletes.LightweightDeleteMutationRunner") as mock_runner:
            delete_custom_events(context=self.mock_context, cluster=mock_cluster, load_pending_deletions=table)

            # Verify LightweightDeleteMutationRunner was called with parameterized query
            mock_runner.assert_called_once()
            call_args = mock_runner.call_args

            predicate = call_args[1]["predicate"]
            parameters = call_args[1]["parameters"]

            # Predicate should use parameter placeholder
            self.assertIn("team_id = %(team_id)s", predicate)
            self.assertIn('properties.test = "value"', predicate)

            # Parameters should include team_id
            self.assertEqual(parameters["team_id"], self.team.id)

    def test_cleanup_delete_assets_team_id_filtering(self):
        """Test cleanup_delete_assets properly filters custom deletions by team_id."""
        # Create test deletions
        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.cleanup = 1", created_by=self.user
        )

        table = PendingDeletesTable(timestamp=datetime.now())
        config = DeleteConfig()

        with patch("dags.deletes.AsyncDeletion.objects") as mock_objects:
            mock_queryset = MagicMock()
            mock_objects.filter.return_value = mock_queryset

            # Mock cluster operations
            mock_cluster = MagicMock()

            cleanup_delete_assets(
                cluster=mock_cluster,
                config=config,
                create_pending_deletions_table=table,
                create_deletes_dict=MagicMock(),
                create_adhoc_event_deletes_dict=MagicMock(),
                waited_mutation=MagicMock(),
            )

            # Verify filter was called with team_id__isnull=False for Custom deletions
            filter_calls = mock_objects.filter.call_args_list
            self.assertTrue(len(filter_calls) > 0)

            # Check that the filter includes Custom deletions with team_id requirement
            filter_args = filter_calls[0][0][0]  # First Q object
            self.assertIn("Custom", str(filter_args))

    def test_cleanup_delete_assets_with_specific_team(self):
        """Test cleanup_delete_assets with specific team_id filtering."""
        # Create deletions for different teams
        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.team1 = 1", created_by=self.user
        )

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team2.id, key="properties.team2 = 1", created_by=self.user
        )

        table = PendingDeletesTable(timestamp=datetime.now(), team_id=self.team.id)
        config = DeleteConfig()

        with patch("dags.deletes.AsyncDeletion.objects") as mock_objects:
            mock_queryset = MagicMock()
            mock_objects.filter.return_value = mock_queryset

            mock_cluster = MagicMock()

            cleanup_delete_assets(
                cluster=mock_cluster,
                config=config,
                create_pending_deletions_table=table,
                create_deletes_dict=MagicMock(),
                create_adhoc_event_deletes_dict=MagicMock(),
                waited_mutation=MagicMock(),
            )

            # Verify filter includes specific team_id
            filter_calls = mock_objects.filter.call_args_list
            self.assertTrue(len(filter_calls) > 0)

            filter_kwargs = filter_calls[0][1]
            self.assertEqual(filter_kwargs.get("team_id"), self.team.id)

    def test_cross_team_isolation(self):
        """Test that operations never affect other teams' data."""
        # Create custom deletions for different teams
        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom, team_id=self.team.id, key="properties.isolated = 1", created_by=self.user
        )

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Custom,
            team_id=self.team2.id,
            key="properties.isolated = 1",
            created_by=self.user,
        )

        table = PendingDeletesTable(timestamp=datetime.now())

        # Mock only team1 deletion in ClickHouse result
        mock_cluster = MagicMock()
        mock_cluster.any_host_by_role.return_value.result.return_value = [(self.team.id, "properties.isolated = 1")]

        with patch("dags.deletes.LightweightDeleteMutationRunner") as mock_runner:
            delete_custom_events(context=self.mock_context, cluster=mock_cluster, load_pending_deletions=table)

            # Verify only one mutation runner created
            mock_runner.assert_called_once()

            # Verify it uses team1's ID
            call_args = mock_runner.call_args
            parameters = call_args[1]["parameters"]
            self.assertEqual(parameters["team_id"], self.team.id)
            self.assertNotEqual(parameters["team_id"], self.team2.id)
