import pytest
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_HOURLY_HISTORICAL_SQL,
    WEB_BOUNCES_HOURLY_HISTORICAL_SQL, 
    WEB_STATS_HOURLY_COMBINED_VIEW_SQL,
    WEB_BOUNCES_HOURLY_COMBINED_VIEW_SQL,
    HISTORICAL_HOURLY_TABLE_TEMPLATE,
    create_hourly_combined_view_sql,
    WEB_STATS_INSERT_SQL,
    WEB_BOUNCES_INSERT_SQL,
)


class TestHourlyHistoricalTableCreation:
    """Test the SQL generation for creating hourly historical tables."""

    def test_web_stats_hourly_historical_table_sql(self):
        sql = WEB_STATS_HOURLY_HISTORICAL_SQL()
        
        # Should create the correct table name
        assert "web_stats_hourly_historical" in sql
        assert "CREATE TABLE IF NOT EXISTS" in sql
        
        # Should use daily partitions (not hourly like the current hourly tables)
        assert "PARTITION BY toYYYYMMDD(period_bucket)" in sql
        assert "formatDateTime" not in sql  # No hourly partitions
        
        # Should not have TTL (historical data)
        assert "TTL" not in sql
        
        # Should have all required columns
        expected_columns = [
            "period_bucket DateTime",
            "team_id UInt64", 
            "host String",
            "device_type String",
            "pathname String",
            "persons_uniq_state AggregateFunction(uniq, UUID)",
            "sessions_uniq_state AggregateFunction(uniq, String)",
            "pageviews_count_state AggregateFunction(sum, UInt64)"
        ]
        
        for column in expected_columns:
            assert column in sql

    def test_web_bounces_hourly_historical_table_sql(self):
        sql = WEB_BOUNCES_HOURLY_HISTORICAL_SQL()
        
        assert "web_bounces_hourly_historical" in sql
        assert "PARTITION BY toYYYYMMDD(period_bucket)" in sql
        assert "TTL" not in sql
        
        # Should have bounces-specific columns
        assert "bounces_count_state AggregateFunction(sum, UInt64)" in sql
        assert "total_session_duration_state AggregateFunction(sum, Int64)" in sql

    def test_custom_table_name_support(self):
        custom_sql = WEB_STATS_HOURLY_HISTORICAL_SQL("custom_web_stats_table")
        
        assert "custom_web_stats_table" in custom_sql
        assert "web_stats_hourly_historical" not in custom_sql

    def test_historical_hourly_table_template(self):
        sql = HISTORICAL_HOURLY_TABLE_TEMPLATE(
            "test_table",
            "test_column String",
            "(team_id, period_bucket)"
        )
        
        assert "CREATE TABLE IF NOT EXISTS test_table" in sql
        assert "test_column String" in sql
        assert "ORDER BY (team_id, period_bucket)" in sql
        assert "PARTITION BY toYYYYMMDD(period_bucket)" in sql


class TestHourlyCombinedViews:
    """Test the combined views that merge historical + current day data."""

    def test_web_stats_hourly_combined_view_sql(self):
        sql = WEB_STATS_HOURLY_COMBINED_VIEW_SQL()
        
        # Should create the correct view name
        assert "web_stats_hourly_combined" in sql
        assert "CREATE OR REPLACE VIEW" in sql
        
        # Should combine historical (before today) + current (today)
        assert "FROM web_stats_hourly_historical" in sql
        assert "FROM web_stats_hourly" in sql
        assert "UNION ALL" in sql
        
        # Should split on today's boundary
        assert "WHERE period_bucket < toStartOfDay(now(), 'UTC')" in sql
        assert "WHERE period_bucket >= toStartOfDay(now(), 'UTC')" in sql

    def test_web_bounces_hourly_combined_view_sql(self):
        sql = WEB_BOUNCES_HOURLY_COMBINED_VIEW_SQL()
        
        assert "web_bounces_hourly_combined" in sql
        assert "FROM web_bounces_hourly_historical" in sql
        assert "FROM web_bounces_hourly" in sql

    def test_create_hourly_combined_view_template(self):
        sql = create_hourly_combined_view_sql("test_prefix")
        
        assert "test_prefix_hourly_combined" in sql
        assert "FROM test_prefix_hourly_historical" in sql
        assert "FROM test_prefix_hourly" in sql


class TestHourlyGranularityDataInsertion:
    """Test that the insert SQL works correctly with hourly granularity."""

    def test_web_stats_insert_hourly_granularity(self):
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[1, 2],
            table_name="web_stats_hourly_historical",
            granularity="hourly"
        )
        
        # Should use toStartOfHour for period bucketing
        assert "toStartOfHour(start_timestamp) AS period_bucket" in sql
        assert "toStartOfDay(start_timestamp)" not in sql
        
        # Should insert into the correct table
        assert "INSERT INTO web_stats_hourly_historical" in sql

    def test_web_bounces_insert_hourly_granularity(self):
        sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01", 
            date_end="2024-01-02",
            team_ids=[1, 2],
            table_name="web_bounces_hourly_historical",
            granularity="hourly"
        )
        
        assert "toStartOfHour(start_timestamp) AS period_bucket" in sql
        assert "INSERT INTO web_bounces_hourly_historical" in sql

    def test_staging_table_insert(self):
        """Test inserting into staging table for atomic operations."""
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02", 
            team_ids=[1],
            table_name="web_stats_hourly_historical_staging",
            granularity="hourly"
        )
        
        assert "INSERT INTO web_stats_hourly_historical_staging" in sql

    def test_timezone_parameter_usage(self):
        """Test that timezone parameter works with hourly granularity."""
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            timezone="America/Los_Angeles",
            granularity="hourly",
            select_only=True
        )
        
        # Should convert timestamps to specified timezone
        assert "toTimeZone(e.timestamp, 'America/Los_Angeles')" in sql
        assert "toTimeZone(raw_sessions.min_timestamp, 'America/Los_Angeles')" in sql

    def test_team_filtering_with_hourly_granularity(self):
        """Test team filtering works correctly with hourly tables."""
        # With explicit team IDs
        sql_teams = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[1, 2, 3],
            granularity="hourly",
            select_only=True
        )
        assert "team_id IN(1, 2, 3)" in sql_teams
        
        # With dictionary lookup
        sql_dict = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02", 
            team_ids=None,
            granularity="hourly",
            select_only=True
        )
        assert "dictHas(" in sql_dict


class TestTimezoneImprovements:
    """Test that the hourly approach provides better timezone handling."""

    def test_hourly_buckets_vs_daily_buckets(self):
        """
        Demonstrate the timezone improvement: hourly buckets align better 
        with user's local time boundaries than daily UTC buckets.
        """
        # Daily granularity (existing approach)
        daily_sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            timezone="America/Los_Angeles",
            granularity="daily",
            select_only=True
        )
        
        # Hourly granularity (new approach) 
        hourly_sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            timezone="America/Los_Angeles", 
            granularity="hourly",
            select_only=True
        )
        
        # Daily uses day boundaries
        assert "toStartOfDay(start_timestamp)" in daily_sql
        
        # Hourly uses hour boundaries (better for timezone alignment)
        assert "toStartOfHour(start_timestamp)" in hourly_sql
        
        # Both should respect the timezone parameter
        assert "America/Los_Angeles" in daily_sql
        assert "America/Los_Angeles" in hourly_sql

    def test_partition_strategy_maintains_performance(self):
        """
        Verify that despite hourly bucketing, we maintain daily partitions
        for efficient data management and backfills.
        """
        create_sql = WEB_STATS_HOURLY_HISTORICAL_SQL()
        
        # Daily partitions (efficient for management)
        assert "PARTITION BY toYYYYMMDD(period_bucket)" in create_sql
        
        # NOT hourly partitions (would be too many small partitions)
        assert "formatDateTime(period_bucket, '%Y%m%d%H')" not in create_sql

    def test_view_seamlessly_combines_data_sources(self):
        """
        Test that the combined view provides seamless access to both
        historical hourly data and current day hourly data.
        """
        view_sql = WEB_STATS_HOURLY_COMBINED_VIEW_SQL()
        
        # Historical data (complete days before today)
        assert "FROM web_stats_hourly_historical WHERE period_bucket < toStartOfDay(now(), 'UTC')" in view_sql
        
        # Current day data (today's partial data)
        assert "FROM web_stats_hourly WHERE period_bucket >= toStartOfDay(now(), 'UTC')" in view_sql
        
        # Seamless union
        assert "UNION ALL" in view_sql