"""
Simple integration tests for partition drop functionality.
Tests the actual ClickHouse partition operations without complex data.
"""
import pytest

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.web_preaggregated.sql import (
    DROP_PARTITION_SQL,
    DROP_PARTITION_IF_EXISTS_SQL,
    CHECK_PARTITION_EXISTS_SQL,
)
from posthog.test.base import APIBaseTest


class TestPartitionDropSimple(APIBaseTest):
    """Simple tests for partition drop functionality with real ClickHouse operations."""

    def setUp(self):
        super().setUp()
        self.test_table_monthly = f"test_monthly_partition_{self.team.pk}"
        self.test_table_hourly = f"test_hourly_partition_{self.team.pk}"

    def tearDown(self):
        """Clean up test tables."""
        super().tearDown()
        for table in [self.test_table_monthly, self.test_table_hourly]:
            try:
                sync_execute(f"DROP TABLE IF EXISTS {table}")
            except:
                pass

    def _create_simple_monthly_table(self):
        """Create a simple table with monthly partitioning."""
        sql = f"""
        CREATE TABLE IF NOT EXISTS {self.test_table_monthly}
        (
            period_bucket DateTime,
            team_id UInt64,
            value String,
            created_at DateTime64(6, 'UTC') DEFAULT now()
        )
        ENGINE = MergeTree()
        PARTITION BY toYYYYMM(period_bucket)
        ORDER BY (team_id, period_bucket)
        """
        sync_execute(sql)

    def _create_simple_hourly_table(self):
        """Create a simple table with hourly partitioning.""" 
        sql = f"""
        CREATE TABLE IF NOT EXISTS {self.test_table_hourly}
        (
            period_bucket DateTime,
            team_id UInt64,
            value String,
            created_at DateTime64(6, 'UTC') DEFAULT now()
        )
        ENGINE = MergeTree()
        PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')
        ORDER BY (team_id, period_bucket)
        """
        sync_execute(sql)

    def _insert_simple_data(self, table_name, date_str, value_suffix=""):
        """Insert simple test data."""
        sql = f"""
        INSERT INTO {table_name} (period_bucket, team_id, value)
        VALUES ('{date_str}', {self.team.pk}, 'test_value{value_suffix}')
        """
        sync_execute(sql)

    def _drop_partition_if_exists(self, table_name, date_start, granularity="daily"):
        """Safely drop a partition only if it exists."""
        check_sql = CHECK_PARTITION_EXISTS_SQL(table_name, date_start, granularity)
        exists = sync_execute(check_sql)[0][0] > 0
        
        if exists:
            drop_sql = DROP_PARTITION_SQL(table_name, date_start, on_cluster=False, granularity=granularity)
            sync_execute(drop_sql)
        
        return exists

    def test_monthly_partition_drop_basic(self):
        """Test basic monthly partition drop functionality."""
        self._create_simple_monthly_table()
        
        # Insert data for January 2024
        self._insert_simple_data(self.test_table_monthly, "2024-01-15 10:00:00", "_jan")
        
        # Verify data exists
        count_sql = f"SELECT count(*) FROM {self.test_table_monthly} WHERE team_id = {self.team.pk}"
        initial_count = sync_execute(count_sql)[0][0]
        assert initial_count == 1
        
        # Drop January partition (202401)
        was_dropped = self._drop_partition_if_exists(self.test_table_monthly, "2024-01-15")
        assert was_dropped  # Verify partition was found and dropped
        
        # Verify data is gone
        count_after_drop = sync_execute(count_sql)[0][0]
        assert count_after_drop == 0
        
        # Insert data again
        self._insert_simple_data(self.test_table_monthly, "2024-01-15 10:00:00", "_jan_restored")
        
        # Verify data is back
        final_count = sync_execute(count_sql)[0][0]
        assert final_count == 1

    def test_hourly_partition_drop_basic(self):
        """Test basic hourly partition drop functionality."""
        self._create_simple_hourly_table()
        
        # Insert data for specific hour
        self._insert_simple_data(self.test_table_hourly, "2024-01-15 14:00:00", "_14h")
        
        # Verify data exists
        count_sql = f"SELECT count(*) FROM {self.test_table_hourly} WHERE team_id = {self.team.pk}"
        initial_count = sync_execute(count_sql)[0][0]
        assert initial_count == 1
        
        # Drop hour partition (2024011514)
        was_dropped = self._drop_partition_if_exists(self.test_table_hourly, "2024-01-15 14", granularity="hourly")
        assert was_dropped  # Verify partition was found and dropped
        
        # Verify data is gone
        count_after_drop = sync_execute(count_sql)[0][0]
        assert count_after_drop == 0

    def test_partition_drop_if_exists_safety(self):
        """Test that DROP PARTITION IF EXISTS doesn't fail for non-existent partitions."""
        self._create_simple_monthly_table()
        
        # Try to drop non-existent partition - should not fail
        was_dropped = self._drop_partition_if_exists(self.test_table_monthly, "2099-12-31")
        
        # Should succeed even though partition doesn't exist (just returns False)
        assert not was_dropped, "Should return False for non-existent partition"

    def test_partition_drop_without_if_exists_succeeds(self):
        """Test that regular DROP PARTITION succeeds even for non-existent partitions (ClickHouse behavior)."""
        self._create_simple_monthly_table()
        
        # Try to drop non-existent partition - ClickHouse doesn't fail for this
        drop_sql = DROP_PARTITION_SQL(self.test_table_monthly, "2099-12-31", on_cluster=False)
        
        # This should succeed without error (ClickHouse behavior)
        try:
            sync_execute(drop_sql)
            success = True
        except Exception as e:
            success = False
            print(f"Unexpected error: {e}")
        
        assert success, "ClickHouse should allow dropping non-existent partitions"

    def test_cross_month_partition_isolation(self):
        """Test that dropping one month's partition doesn't affect other months."""
        self._create_simple_monthly_table()
        
        # Insert data for January and February
        self._insert_simple_data(self.test_table_monthly, "2024-01-15 10:00:00", "_jan")
        self._insert_simple_data(self.test_table_monthly, "2024-02-15 10:00:00", "_feb")
        
        # Verify both months have data
        jan_count = sync_execute(f"SELECT count(*) FROM {self.test_table_monthly} WHERE toYYYYMM(period_bucket) = 202401")[0][0]
        feb_count = sync_execute(f"SELECT count(*) FROM {self.test_table_monthly} WHERE toYYYYMM(period_bucket) = 202402")[0][0]
        
        assert jan_count == 1
        assert feb_count == 1
        
        # Drop only January partition
        was_dropped = self._drop_partition_if_exists(self.test_table_monthly, "2024-01-15")
        assert was_dropped
        
        # Verify only January data is gone
        jan_count_after = sync_execute(f"SELECT count(*) FROM {self.test_table_monthly} WHERE toYYYYMM(period_bucket) = 202401")[0][0]
        feb_count_after = sync_execute(f"SELECT count(*) FROM {self.test_table_monthly} WHERE toYYYYMM(period_bucket) = 202402")[0][0]
        
        assert jan_count_after == 0
        assert feb_count_after == 1  # February should be unchanged

    def test_hourly_partition_format_variations(self):
        """Test different hourly partition format inputs."""
        self._create_simple_hourly_table()
        
        # Test with hour specified
        drop_sql_with_hour = DROP_PARTITION_SQL(self.test_table_hourly, "2024-01-15 14", on_cluster=False, granularity="hourly")
        assert "'2024011514'" in drop_sql_with_hour
        
        # Test without hour (should default to 00)
        drop_sql_no_hour = DROP_PARTITION_SQL(self.test_table_hourly, "2024-01-15", on_cluster=False, granularity="hourly")
        assert "'2024011500'" in drop_sql_no_hour
        
        # Test with single digit hour (should be zero-padded)
        drop_sql_single_digit = DROP_PARTITION_SQL(self.test_table_hourly, "2024-01-15 5", on_cluster=False, granularity="hourly")
        assert "'2024011505'" in drop_sql_single_digit

    def test_idempotent_dag_workflow_simulation(self):
        """Simulate the DAG workflow of drop + insert for idempotency."""
        self._create_simple_monthly_table()
        
        def simulate_dag_run(run_id):
            """Simulate one DAG run: drop partition + insert data."""
            # Step 1: Drop partition for idempotency
            self._drop_partition_if_exists(self.test_table_monthly, "2024-01-15")
            
            # Step 2: Insert fresh data
            self._insert_simple_data(self.test_table_monthly, "2024-01-15 10:00:00", f"_run{run_id}")
        
        # Run the simulation 3 times
        for run_id in range(1, 4):
            simulate_dag_run(run_id)
            
            # After each run, verify we have exactly 1 row
            count = sync_execute(f"SELECT count(*) FROM {self.test_table_monthly} WHERE team_id = {self.team.pk}")[0][0]
            assert count == 1, f"Run {run_id}: Expected 1 row, got {count}"
            
            # Verify the value shows it's from the current run (last insert wins)
            value = sync_execute(f"SELECT value FROM {self.test_table_monthly} WHERE team_id = {self.team.pk}")[0][0]
            assert value == f"test_value_run{run_id}", f"Run {run_id}: Expected value from current run"

    def test_partition_metadata_verification(self):
        """Test that we can query partition information to verify drops."""
        self._create_simple_monthly_table()
        
        # Insert data
        self._insert_simple_data(self.test_table_monthly, "2024-01-15 10:00:00")
        
        # Check partition exists in system.parts
        partitions_before = sync_execute(f"""
            SELECT DISTINCT partition
            FROM system.parts
            WHERE table = '{self.test_table_monthly}'
            AND database = currentDatabase()
            AND active = 1
        """)
        
        assert len(partitions_before) == 1
        assert partitions_before[0][0] == "202401"
        
        # Drop partition
        was_dropped = self._drop_partition_if_exists(self.test_table_monthly, "2024-01-15")
        assert was_dropped
        
        # Check partition no longer exists
        partitions_after = sync_execute(f"""
            SELECT DISTINCT partition
            FROM system.parts
            WHERE table = '{self.test_table_monthly}'
            AND database = currentDatabase()
            AND active = 1
        """)
        
        assert len(partitions_after) == 0 