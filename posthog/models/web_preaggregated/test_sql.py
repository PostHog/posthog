"""
Tests for web preaggregated SQL generation functions.
"""

import pytest
from unittest.mock import patch
from posthog.models.web_preaggregated.sql import (
    DROP_PARTITION_SQL,
    DROP_PARTITION_IF_EXISTS_SQL,
    TABLE_TEMPLATE,
    HOURLY_TABLE_TEMPLATE,
    WEB_STATS_COLUMNS,
    WEB_BOUNCES_COLUMNS,
    WEB_STATS_ORDER_BY_FUNC,
    WEB_BOUNCES_ORDER_BY_FUNC,
)


class TestPartitionDropSQL:
    """Test partition drop SQL generation for both daily and hourly granularity."""

    def test_drop_partition_daily_format(self):
        """Test daily partition drop SQL generation."""
        sql = DROP_PARTITION_SQL("web_stats_daily", "2024-01-15", on_cluster=False)

        expected = """
    ALTER TABLE web_stats_daily
    DROP PARTITION '20240115'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_daily_with_cluster(self):
        """Test daily partition drop SQL with cluster."""
        with patch("posthog.models.web_preaggregated.sql.CLICKHOUSE_CLUSTER", "test_cluster"):
            sql = DROP_PARTITION_SQL("web_stats_daily", "2024-01-15", on_cluster=True)

            expected = """
    ALTER TABLE web_stats_daily ON CLUSTER 'test_cluster'
    DROP PARTITION '20240115'
    """
            assert sql.strip() == expected.strip()

    def test_drop_partition_hourly_with_hour(self):
        """Test hourly partition drop SQL with hour specified."""
        sql = DROP_PARTITION_SQL("web_stats_hourly", "2024-01-15 14", on_cluster=False, granularity="hourly")

        expected = """
    ALTER TABLE web_stats_hourly
    DROP PARTITION '2024011514'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_hourly_without_hour(self):
        """Test hourly partition drop SQL without hour (defaults to 00)."""
        sql = DROP_PARTITION_SQL("web_stats_hourly", "2024-01-15", on_cluster=False, granularity="hourly")

        expected = """
    ALTER TABLE web_stats_hourly
    DROP PARTITION '2024011500'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_hourly_single_digit_hour(self):
        """Test hourly partition drop SQL with single digit hour (should be zero-padded)."""
        sql = DROP_PARTITION_SQL("web_stats_hourly", "2024-01-15 5", on_cluster=False, granularity="hourly")

        expected = """
    ALTER TABLE web_stats_hourly
    DROP PARTITION '2024011505'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_if_exists_daily(self):
        """Test daily partition drop IF EXISTS SQL generation."""
        sql = DROP_PARTITION_IF_EXISTS_SQL("web_bounces_daily", "2024-01-15", on_cluster=False)

        expected = """
    ALTER TABLE web_bounces_daily
    DROP PARTITION IF EXISTS '20240115'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_if_exists_hourly(self):
        """Test hourly partition drop IF EXISTS SQL generation."""
        sql = DROP_PARTITION_IF_EXISTS_SQL(
            "web_bounces_hourly", "2024-01-15 08", on_cluster=False, granularity="hourly"
        )

        expected = """
    ALTER TABLE web_bounces_hourly
    DROP PARTITION IF EXISTS '2024011508'
    """
        assert sql.strip() == expected.strip()


class TestTableTemplates:
    """Test table creation templates with correct partitioning."""

    def test_daily_table_partition_by_date(self):
        """Test that daily tables are partitioned by YYYYMMDD."""
        sql = TABLE_TEMPLATE("web_stats_daily", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC(), on_cluster=False)

        assert "PARTITION BY toYYYYMMDD(period_bucket)" in sql
        assert "web_stats_daily" in sql

    def test_hourly_table_partition_by_hour(self):
        """Test that hourly tables are partitioned by YYYYMMDDhh."""
        sql = HOURLY_TABLE_TEMPLATE("web_stats_hourly", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC(), on_cluster=False)

        assert "PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')" in sql
        assert "web_stats_hourly" in sql

    def test_hourly_table_with_ttl(self):
        """Test hourly table template with TTL."""
        sql = HOURLY_TABLE_TEMPLATE(
            "web_stats_hourly", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC(), on_cluster=False, ttl="24 HOUR"
        )

        assert "PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')" in sql
        assert "TTL period_bucket + INTERVAL 24 HOUR DELETE" in sql

    def test_daily_table_with_cluster(self):
        """Test daily table template with cluster."""
        with patch("posthog.models.web_preaggregated.sql.CLICKHOUSE_CLUSTER", "test_cluster"):
            sql = TABLE_TEMPLATE("web_bounces_daily", WEB_BOUNCES_COLUMNS, WEB_BOUNCES_ORDER_BY_FUNC(), on_cluster=True)

            assert "ON CLUSTER 'test_cluster'" in sql
            assert "PARTITION BY toYYYYMMDD(period_bucket)" in sql

    def test_hourly_table_with_cluster(self):
        """Test hourly table template with cluster."""
        with patch("posthog.models.web_preaggregated.sql.CLICKHOUSE_CLUSTER", "test_cluster"):
            sql = HOURLY_TABLE_TEMPLATE(
                "web_bounces_hourly", WEB_BOUNCES_COLUMNS, WEB_BOUNCES_ORDER_BY_FUNC(), on_cluster=True, ttl="24 HOUR"
            )

            assert "ON CLUSTER 'test_cluster'" in sql
            assert "PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')" in sql
            assert "TTL period_bucket + INTERVAL 24 HOUR DELETE" in sql


class TestPartitionIDFormatting:
    """Test edge cases for partition ID formatting."""

    @pytest.mark.parametrize(
        "date_input,granularity,expected_partition",
        [
            ("2024-01-01", "daily", "20240101"),
            ("2024-12-31", "daily", "20241231"),
            ("2024-01-01", "hourly", "2024010100"),
            ("2024-01-01 23", "hourly", "2024010123"),
            ("2024-01-01 0", "hourly", "2024010100"),
            ("2024-01-01 9", "hourly", "2024010109"),
        ],
    )
    def test_partition_id_formatting(self, date_input, granularity, expected_partition):
        """Test various date inputs produce correct partition IDs."""
        sql = DROP_PARTITION_IF_EXISTS_SQL("test_table", date_input, on_cluster=False, granularity=granularity)
        assert f"'{expected_partition}'" in sql

    def test_invalid_hourly_format_defaults_to_00(self):
        """Test that malformed hourly input defaults gracefully."""
        # Test with date only for hourly granularity
        sql = DROP_PARTITION_IF_EXISTS_SQL("test_table", "2024-01-15", on_cluster=False, granularity="hourly")
        assert "'2024011500'" in sql


class TestHourlyPartitioningIntegration:
    """Test cases for hourly partitioning integration (for future hourly DAGs)."""

    def test_hourly_partition_drop_for_different_hours(self):
        """Test that different hours generate different partition IDs."""
        test_cases = [
            ("2024-01-15 00", "2024011500"),
            ("2024-01-15 01", "2024011501"),
            ("2024-01-15 12", "2024011512"),
            ("2024-01-15 23", "2024011523"),
        ]

        for date_input, expected_partition in test_cases:
            sql = DROP_PARTITION_IF_EXISTS_SQL("web_stats_hourly", date_input, on_cluster=False, granularity="hourly")
            assert f"'{expected_partition}'" in sql

    def test_hourly_table_creation_with_ttl(self):
        """Test that hourly tables have proper TTL and partitioning."""
        sql = HOURLY_TABLE_TEMPLATE(
            "web_stats_hourly", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC(), on_cluster=False, ttl="24 HOUR"
        )

        # Should have hourly partitioning
        assert "PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')" in sql
        # Should have TTL
        assert "TTL period_bucket + INTERVAL 24 HOUR DELETE" in sql
        # Should be MergeTree (migrated from ReplacingMergeTree)
        assert "ReplicatedMergeTree" in sql

    def test_hourly_vs_daily_partition_difference(self):
        """Test that hourly and daily partitions produce different results."""
        date = "2024-01-15"

        daily_sql = DROP_PARTITION_IF_EXISTS_SQL("web_stats_daily", date, on_cluster=False, granularity="daily")
        hourly_sql = DROP_PARTITION_IF_EXISTS_SQL("web_stats_hourly", date, on_cluster=False, granularity="hourly")

        # Daily should be YYYYMMDD format
        assert "'20240115'" in daily_sql
        # Hourly should be YYYYMMDDHH format (defaulting to 00)
        assert "'2024011500'" in hourly_sql

        # They should be different
        assert "'20240115'" not in hourly_sql
        assert "'2024011500'" not in daily_sql
