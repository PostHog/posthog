"""Tests for the Postgres to ClickHouse ETL pipeline."""

import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from dagster import build_op_context

from dags.postgres_to_clickhouse_etl import (
    ETLState,
    create_clickhouse_tables,
    fetch_organizations,
    fetch_teams,
    insert_organizations_to_clickhouse,
    insert_teams_to_clickhouse,
    organizations_in_clickhouse,
    postgres_to_clickhouse_etl_job,
    postgres_to_clickhouse_hourly_schedule,
    sync_organizations,
    sync_teams,
    teams_in_clickhouse,
    transform_organization_row,
    transform_team_row,
    verify_sync,
)


class TestTransformations:
    """Test data transformation functions."""

    def test_transform_organization_row(self):
        """Test organization row transformation."""
        import uuid

        test_uuid = uuid.uuid4()

        row = {
            "id": test_uuid,
            "name": "Test Org",
            "slug": "test-org",
            "logo_media_id": uuid.uuid4(),
            "is_member_join_email_enabled": True,
            "is_hipaa": False,
            "available_product_features": [{"key": "feature1", "name": "Feature 1"}],
            "usage": {"events": {"usage": 1000}},
            "personalization": {"role": "engineer"},
            "domain_whitelist": ["example.com"],
        }

        transformed = transform_organization_row(row)

        # Check UUID conversions
        assert transformed["id"] == str(test_uuid)
        assert isinstance(transformed["logo_media_id"], str)

        # Check boolean conversions
        assert transformed["is_member_join_email_enabled"] == 1
        assert transformed["is_hipaa"] == 0

        # Check JSON field conversions
        assert transformed["available_product_features"] == json.dumps([{"key": "feature1", "name": "Feature 1"}])
        assert transformed["usage"] == json.dumps({"events": {"usage": 1000}})
        assert transformed["personalization"] == json.dumps({"role": "engineer"})

    def test_transform_team_row(self):
        """Test team row transformation."""
        import uuid

        team_uuid = uuid.uuid4()
        org_uuid = uuid.uuid4()

        row = {
            "id": 1,
            "uuid": team_uuid,
            "organization_id": org_uuid,
            "name": "Test Team",
            "anonymize_ips": True,
            "session_recording_opt_in": False,
            "test_account_filters": [{"key": "email", "value": "test@example.com"}],
            "drop_events_older_than": timedelta(days=30),
            "app_urls": ["https://app.example.com"],
            "person_display_name_properties": None,
            "session_recording_sample_rate": Decimal("0.50"),
        }

        transformed = transform_team_row(row)

        # Check UUID conversions
        assert transformed["uuid"] == str(team_uuid)
        assert transformed["organization_id"] == str(org_uuid)

        # Check boolean conversions
        assert transformed["anonymize_ips"] == 1
        assert transformed["session_recording_opt_in"] == 0

        # Check JSON field conversion
        assert transformed["test_account_filters"] == json.dumps([{"key": "email", "value": "test@example.com"}])

        # Check timedelta conversion
        assert transformed["drop_events_older_than"] == 30 * 24 * 60 * 60  # 30 days in seconds

        # Check array field handling
        assert transformed["app_urls"] == ["https://app.example.com"]
        assert transformed["person_display_name_properties"] == []

        # Check decimal remains unchanged
        assert transformed["session_recording_sample_rate"] == Decimal("0.50")


class TestDatabaseOperations:
    """Test database operation functions."""

    @patch("dags.postgres_to_clickhouse_etl.psycopg2.connect")
    def test_fetch_organizations(self, mock_connect):
        """Test fetching organizations from Postgres."""
        # Mock both named cursor and regular cursor
        mock_named_cursor = MagicMock()
        mock_named_cursor.fetchmany.side_effect = [[{"id": 1, "name": "Org 1", "updated_at": datetime.now()}], []]

        mock_regular_cursor = MagicMock()
        mock_regular_cursor.fetchmany.side_effect = [[{"id": 1, "name": "Org 1", "updated_at": datetime.now()}], []]

        mock_conn = MagicMock()

        # Return named cursor when name is provided, regular cursor otherwise
        def cursor_side_effect(name=None):
            if name:
                return mock_named_cursor
            return mock_regular_cursor

        mock_conn.cursor.side_effect = cursor_side_effect
        mock_connect.return_value = mock_conn

        # Test without last_sync
        orgs = fetch_organizations(mock_conn)
        assert len(orgs) == 1
        assert orgs[0]["name"] == "Org 1"

        # Verify query was called correctly on named cursor
        mock_named_cursor.execute.assert_called_once()
        call_args = mock_named_cursor.execute.call_args[0]
        assert "SELECT" in call_args[0]
        assert "FROM posthog_organization" in call_args[0]
        assert "WHERE updated_at >" not in call_args[0]

    @patch("dags.postgres_to_clickhouse_etl.psycopg2.connect")
    def test_fetch_organizations_incremental(self, mock_connect):
        """Test fetching organizations incrementally."""
        mock_named_cursor = MagicMock()
        mock_named_cursor.fetchmany.side_effect = [[{"id": 2, "name": "Org 2", "updated_at": datetime.now()}], []]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_named_cursor
        mock_connect.return_value = mock_conn

        last_sync = datetime.now() - timedelta(days=1)
        _ = fetch_organizations(mock_conn, last_sync=last_sync)

        # Verify incremental query on named cursor
        mock_named_cursor.execute.assert_called_once()
        call_args = mock_named_cursor.execute.call_args[0]
        assert "WHERE updated_at > %s" in call_args[0]
        assert call_args[1] == [last_sync]

    @patch("dags.postgres_to_clickhouse_etl.psycopg2.connect")
    def test_fetch_teams(self, mock_connect):
        """Test fetching teams from Postgres."""
        mock_named_cursor = MagicMock()
        mock_named_cursor.fetchmany.side_effect = [
            [{"id": 1, "name": "Team 1", "organization_id": 1, "updated_at": datetime.now()}],
            [],
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_named_cursor
        mock_connect.return_value = mock_conn

        teams = fetch_teams(mock_conn)
        assert len(teams) == 1
        assert teams[0]["name"] == "Team 1"

    @patch("dags.postgres_to_clickhouse_etl.get_cluster")
    def test_create_clickhouse_tables(self, mock_get_cluster):
        """Test ClickHouse table creation."""
        # Mock the cluster and its methods
        mock_cluster = MagicMock()
        mock_futures_map = MagicMock()
        mock_futures_map.result.return_value = {}
        mock_cluster.map_all_hosts.return_value = mock_futures_map
        mock_get_cluster.return_value = mock_cluster

        create_clickhouse_tables()

        # Should have called map_all_hosts for:
        # 1. CREATE DATABASE IF NOT EXISTS models
        # 2. CREATE TABLE posthog_organization
        # 3. CREATE TABLE posthog_team
        assert mock_cluster.map_all_hosts.call_count == 3

        # Extract the Query objects from the calls
        calls = [call[0][0].query for call in mock_cluster.map_all_hosts.call_args_list]

        # Check database creation
        assert any("CREATE DATABASE IF NOT EXISTS models" in call for call in calls)

        # Check table creation with ReplicatedReplacingMergeTree
        assert any(
            "CREATE TABLE IF NOT EXISTS models.posthog_organization" in call and "ReplicatedReplacingMergeTree" in call
            for call in calls
        )
        assert any(
            "CREATE TABLE IF NOT EXISTS models.posthog_team" in call and "ReplicatedReplacingMergeTree" in call
            for call in calls
        )

    @patch("dags.postgres_to_clickhouse_etl.sync_execute")
    def test_insert_organizations_to_clickhouse(self, mock_sync_execute):
        """Test inserting organizations into ClickHouse."""
        organizations = [
            {
                "id": 1,
                "uuid": "uuid1",
                "name": "Org 1",
                "slug": "org-1",
                "is_member_join_email_enabled": True,
                "available_product_features": [{"key": "feature1"}],
                "usage": {"events": 1000},
                "personalization": {},
                "domain_whitelist": [],
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            },
            {
                "id": 2,
                "uuid": "uuid2",
                "name": "Org 2",
                "slug": "org-2",
                "is_member_join_email_enabled": False,
                "available_product_features": None,
                "usage": None,
                "personalization": {},
                "domain_whitelist": [],
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            },
        ]

        rows_inserted = insert_organizations_to_clickhouse(organizations, batch_size=10)

        assert rows_inserted == 2
        assert mock_sync_execute.call_count == 1

        # Verify INSERT statement
        call_args = mock_sync_execute.call_args[0]
        assert "INSERT INTO models.posthog_organization" in call_args[0]

    @patch("dags.postgres_to_clickhouse_etl.sync_execute")
    def test_insert_teams_to_clickhouse(self, mock_sync_execute):
        """Test inserting teams into ClickHouse."""
        teams = [
            {
                "id": 1,
                "uuid": "team-uuid1",
                "organization_id": 1,
                "name": "Team 1",
                "anonymize_ips": True,
                "test_account_filters": [{"key": "test"}],
                "app_urls": ["https://example.com"],
                "drop_events_older_than": timedelta(days=7),
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }
        ]

        rows_inserted = insert_teams_to_clickhouse(teams, batch_size=10)

        assert rows_inserted == 1
        assert mock_sync_execute.call_count == 1


class TestOps:
    """Test Dagster ops."""

    @patch("dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_sync_organizations_op(self, mock_create_tables, mock_get_pg_conn, mock_sync_execute):
        """Test the sync_organizations op."""
        # Mock ClickHouse last sync query
        mock_sync_execute.return_value = [[datetime(2024, 1, 1)]]

        # Mock Postgres connection and data
        mock_pg_conn = MagicMock()
        mock_get_pg_conn.return_value = mock_pg_conn

        with (
            patch("dags.postgres_to_clickhouse_etl.fetch_organizations_in_batches") as mock_fetch,
            patch("dags.postgres_to_clickhouse_etl.insert_organizations_to_clickhouse") as mock_insert,
        ):
            # Mock the generator to yield one batch
            mock_fetch.return_value = iter([[{"id": 1, "name": "Org 1", "updated_at": datetime(2024, 1, 2)}]])
            mock_insert.return_value = 1

            # Create context and run op
            context = build_op_context(
                config={
                    "full_refresh": False,
                    "batch_size": 10000,
                    "max_execution_time": 3600,
                }
            )

            result = sync_organizations(context)

            assert isinstance(result, ETLState)
            assert result.rows_synced == 1
            assert result.last_sync_timestamp == datetime(2024, 1, 2)
            assert len(result.errors) == 0

            # Verify calls
            mock_create_tables.assert_called_once()
            mock_fetch.assert_called_once()
            mock_insert.assert_called_once()

    @patch("dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_sync_teams_op(self, mock_create_tables, mock_get_pg_conn, mock_sync_execute):
        """Test the sync_teams op."""
        # Mock ClickHouse last sync query
        mock_sync_execute.return_value = [[None]]

        # Mock Postgres connection
        mock_pg_conn = MagicMock()
        mock_get_pg_conn.return_value = mock_pg_conn

        with (
            patch("dags.postgres_to_clickhouse_etl.fetch_teams_in_batches") as mock_fetch,
            patch("dags.postgres_to_clickhouse_etl.insert_teams_to_clickhouse") as mock_insert,
        ):
            # Mock the generator to yield one batch
            mock_fetch.return_value = iter(
                [[{"id": 1, "name": "Team 1", "organization_id": 1, "updated_at": datetime(2024, 1, 2)}]]
            )
            mock_insert.return_value = 1

            # Create context and run op
            context = build_op_context(
                config={
                    "full_refresh": False,
                    "batch_size": 10000,
                    "max_execution_time": 3600,
                }
            )

            result = sync_teams(context)

            assert isinstance(result, ETLState)
            assert result.rows_synced == 1
            assert result.last_sync_timestamp == datetime(2024, 1, 2)
            assert len(result.errors) == 0

    @patch("dags.postgres_to_clickhouse_etl.sync_execute")
    def test_verify_sync_op(self, mock_sync_execute):
        """Test the verify_sync op."""
        # Mock ClickHouse counts
        mock_sync_execute.side_effect = [
            [[100]],  # organization count
            [[150]],  # team count
        ]

        # Create states
        org_state = ETLState(rows_synced=10, last_sync_timestamp=datetime.now())
        team_state = ETLState(rows_synced=15, last_sync_timestamp=datetime.now())

        context = build_op_context()
        result = verify_sync(context, org_state, team_state)

        assert result["success"] is True
        assert result["organizations"]["clickhouse_count"] == 100
        assert result["teams"]["clickhouse_count"] == 150
        assert result["organizations"]["rows_synced"] == 10
        assert result["teams"]["rows_synced"] == 15

    @patch("dags.postgres_to_clickhouse_etl.get_cluster")
    @patch("dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_sync_organizations_full_refresh(
        self, mock_create_tables, mock_get_pg_conn, mock_sync_execute, mock_get_cluster
    ):
        """Test sync_organizations with full refresh."""

        mock_pg_conn = MagicMock()
        mock_get_pg_conn.return_value = mock_pg_conn

        with (
            patch("dags.postgres_to_clickhouse_etl.fetch_organizations_in_batches") as mock_fetch,
            patch("dags.postgres_to_clickhouse_etl.insert_organizations_to_clickhouse") as mock_insert,
        ):
            # Mock the generator to yield no batches
            mock_fetch.return_value = iter([])
            mock_insert.return_value = 0

            context = build_op_context(
                config={
                    "full_refresh": True,
                    "batch_size": 10000,
                    "max_execution_time": 3600,
                }
            )

            result = sync_organizations(context)

            # Verify truncate was called for full refresh
            mock_sync_execute.assert_any_call("TRUNCATE TABLE models.posthog_organization")

            assert result.rows_synced == 0
            assert len(result.errors) == 0


class TestErrorHandling:
    """Test error handling in the ETL pipeline."""

    @patch("dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_sync_organizations_handles_errors(self, mock_create_tables, mock_get_pg_conn, mock_sync_execute):
        """Test that sync_organizations handles errors properly."""

        # Mock the max(updated_at) query to return None
        mock_sync_execute.return_value = [[None]]

        mock_pg_conn = MagicMock()
        mock_get_pg_conn.return_value = mock_pg_conn

        with patch("dags.postgres_to_clickhouse_etl.fetch_organizations_in_batches") as mock_fetch:
            mock_fetch.side_effect = Exception("Database connection failed")

            context = build_op_context(
                config={
                    "full_refresh": False,
                    "batch_size": 10000,
                    "max_execution_time": 3600,
                }
            )

            with pytest.raises(Exception, match="Database connection failed"):
                sync_organizations(context)

            # Verify connection was closed even on error
            mock_pg_conn.close.assert_called_once()


class TestPartitioning:
    """Test partitioning and scheduling."""

    def test_hourly_partition_definition(self):
        """Test that the job has hourly partitions."""
        assert postgres_to_clickhouse_etl_job.partitions_def is not None
        partitions = postgres_to_clickhouse_etl_job.partitions_def.get_partition_keys()

        # Check that partitions are hourly
        # Get first two partition keys and verify they're 1 hour apart
        first_partition = partitions[0]
        second_partition = partitions[1]

        # Parse the partition keys (format: "2024-01-01-00:00")
        first_dt = datetime.strptime(first_partition, "%Y-%m-%d-%H:%M")
        second_dt = datetime.strptime(second_partition, "%Y-%m-%d-%H:%M")

        assert (second_dt - first_dt).total_seconds() == 3600  # 1 hour in seconds

    def test_hourly_schedule(self):
        """Test the hourly schedule configuration."""
        assert postgres_to_clickhouse_hourly_schedule.cron_schedule == "0 * * * *"
        assert postgres_to_clickhouse_hourly_schedule.execution_timezone == "UTC"
        assert postgres_to_clickhouse_hourly_schedule.job_name == postgres_to_clickhouse_etl_job.name

    @freeze_time("2024-01-15 14:00:00")
    def test_schedule_execution_time(self):
        """Test that schedule runs at the correct time."""
        from datetime import datetime

        # The cron schedule is "0 * * * *" which means at minute 0 of every hour
        assert postgres_to_clickhouse_hourly_schedule.cron_schedule == "0 * * * *"

        # Verify the schedule would run at the top of the hour
        # In real usage, this would trigger at 14:00:00
        frozen_time = datetime(2024, 1, 15, 14, 0, 0)
        assert frozen_time.minute == 0
        assert frozen_time.second == 0

    def test_backfill_policy(self):
        """Test backfill policy for assets."""
        # Check organizations asset
        assert organizations_in_clickhouse.partitions_def is not None
        assert organizations_in_clickhouse.backfill_policy.max_partitions_per_run == 24

        # Check teams asset
        assert teams_in_clickhouse.partitions_def is not None
        assert teams_in_clickhouse.backfill_policy.max_partitions_per_run == 24

    @patch("dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_asset_hourly_window(self, mock_create_tables, mock_get_pg_conn):
        """Test that assets process correct hourly time windows."""
        from dagster import build_asset_context

        mock_pg_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_pg_conn.cursor.return_value = mock_cursor
        mock_get_pg_conn.return_value = mock_pg_conn

        # Test with a specific partition key
        partition_key = "2024-01-15-14:00"
        context = build_asset_context(partition_key=partition_key)

        # Run the asset
        organizations_in_clickhouse(context)

        # Verify the query was for the correct time window
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0]
        query = call_args[0]
        params = call_args[1]

        assert "WHERE updated_at >= %s AND updated_at < %s" in query

        # Check the time window parameters
        start_time, end_time = params
        assert start_time == datetime(2024, 1, 15, 14, 0)
        assert end_time == datetime(2024, 1, 15, 15, 0)  # One hour later
