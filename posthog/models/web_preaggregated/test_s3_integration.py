import pytest
from unittest.mock import patch
from posthog.clickhouse.client.execute import sync_execute
from posthog.models.web_preaggregated.sql import (
    TABLE_TEMPLATE,
    HOURLY_TABLE_TEMPLATE,
    WEB_STATS_COLUMNS,
    WEB_STATS_ORDER_BY_FUNC,
)
from posthog.test.base import BaseTest


class TestS3BackedMergeTreeIntegration(BaseTest):
    """Integration tests for S3BackedMergeTree functionality"""

    @pytest.mark.integration
    def test_create_table_with_s3_storage_policy(self):
        """Test that tables can be created with S3 storage policy"""
        with patch.dict("os.environ", {"WEB_ANALYTICS_STORAGE_POLICY": "s3"}):
            table_name = "test_web_stats_s3"
            
            # Generate CREATE TABLE SQL
            sql = TABLE_TEMPLATE(table_name, WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC())
            
            # Verify SQL contains storage policy
            assert "SETTINGS storage_policy = 's3_policy'" in sql
            
            # Note: Actual table creation would require S3 storage configuration
            # to be properly set up in the test environment
            
    @pytest.mark.integration  
    def test_create_hourly_table_with_s3_storage_policy(self):
        """Test that hourly tables can be created with S3 storage policy"""
        with patch.dict("os.environ", {"WEB_ANALYTICS_STORAGE_POLICY": "s3"}):
            table_name = "test_web_stats_hourly_s3"
            
            # Generate CREATE TABLE SQL
            sql = HOURLY_TABLE_TEMPLATE(table_name, WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC())
            
            # Verify SQL contains storage policy
            assert "SETTINGS storage_policy = 's3_policy'" in sql
            assert "PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')" in sql

    @pytest.mark.integration
    def test_create_table_without_s3_storage_policy(self):
        """Test that tables are created normally without S3 storage policy"""
        with patch.dict("os.environ", {}, clear=True):
            table_name = "test_web_stats_normal"
            
            # Generate CREATE TABLE SQL
            sql = TABLE_TEMPLATE(table_name, WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC())
            
            # Verify SQL does not contain storage policy
            assert "SETTINGS storage_policy" not in sql
            assert "ReplicatedMergeTree" in sql

    @pytest.mark.integration
    def test_s3_configuration_in_sql_output(self):
        """Test that the S3 configuration produces valid ClickHouse SQL"""
        with patch.dict("os.environ", {"WEB_ANALYTICS_STORAGE_POLICY": "s3"}):
            table_name = "web_stats_combined"
            
            sql = TABLE_TEMPLATE(table_name, WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC())
            
            # Verify the complete structure
            assert "CREATE TABLE IF NOT EXISTS" in sql
            assert "ReplicatedMergeTree" in sql
            assert "SETTINGS storage_policy = 's3_policy'" in sql
            assert "ORDER BY" in sql
            assert "PARTITION BY" in sql
            
            # Ensure SQL is well-formed (basic syntax check)
            assert sql.count("(") == sql.count(")")
            assert "ENGINE =" in sql

    def test_environment_variable_precedence(self):
        """Test that environment variable correctly controls storage policy"""
        # Test with s3 setting
        with patch.dict("os.environ", {"WEB_ANALYTICS_STORAGE_POLICY": "s3"}):
            sql_s3 = TABLE_TEMPLATE("test_table", "test_col String", "(test_col)")
            assert "s3_policy" in sql_s3
            
        # Test with default setting  
        with patch.dict("os.environ", {"WEB_ANALYTICS_STORAGE_POLICY": "default"}):
            sql_default = TABLE_TEMPLATE("test_table", "test_col String", "(test_col)")
            assert "s3_policy" not in sql_default
            
        # Test with unset environment
        with patch.dict("os.environ", {}, clear=True):
            sql_unset = TABLE_TEMPLATE("test_table", "test_col String", "(test_col)")
            assert "s3_policy" not in sql_unset