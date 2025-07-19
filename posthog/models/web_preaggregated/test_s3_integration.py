import os
from unittest.mock import patch

from posthog.models.web_preaggregated.sql import (
    WEB_STATS_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
    get_web_analytics_storage_policy,
)


class TestS3Integration:
    def test_get_web_analytics_storage_policy_default(self):
        """Test that the default storage policy returns None."""
        with patch.dict(os.environ, {}, clear=True):
            policy = get_web_analytics_storage_policy()
            assert policy is None

    def test_get_web_analytics_storage_policy_s3(self):
        """Test that S3 storage policy returns 's3_policy'."""
        with patch.dict(os.environ, {"WEB_ANALYTICS_STORAGE_POLICY": "s3"}):
            policy = get_web_analytics_storage_policy()
            assert policy == "s3_policy"

    def test_web_stats_table_with_s3_policy(self):
        """Test that web stats table creation includes S3 storage policy when environment variable is set."""
        with patch.dict(os.environ, {"WEB_ANALYTICS_STORAGE_POLICY": "s3"}):
            sql = WEB_STATS_DAILY_SQL(table_name="web_stats_test_s3")

            # Verify the table name is correct
            assert "web_stats_test_s3" in sql

            # Verify S3 storage policy is included
            assert "SETTINGS storage_policy = 's3_policy'" in sql

            # Verify it's a ReplicatedMergeTree
            assert "ReplicatedMergeTree" in sql

    def test_web_bounces_table_with_s3_policy(self):
        """Test that web bounces table creation includes S3 storage policy when environment variable is set."""
        with patch.dict(os.environ, {"WEB_ANALYTICS_STORAGE_POLICY": "s3"}):
            sql = WEB_BOUNCES_DAILY_SQL(table_name="web_bounces_test_s3")

            # Verify the table name is correct
            assert "web_bounces_test_s3" in sql

            # Verify S3 storage policy is included
            assert "SETTINGS storage_policy = 's3_policy'" in sql

            # Verify it's a ReplicatedMergeTree
            assert "ReplicatedMergeTree" in sql

    def test_web_stats_table_without_s3_policy(self):
        """Test that web stats table creation works without S3 storage policy."""
        with patch.dict(os.environ, {}, clear=True):
            sql = WEB_STATS_DAILY_SQL(table_name="web_stats_test_default")

            # Verify the table name is correct
            assert "web_stats_test_default" in sql

            # Verify no storage policy is mentioned
            assert "storage_policy" not in sql

            # Verify it's still a ReplicatedMergeTree
            assert "ReplicatedMergeTree" in sql

    def test_web_bounces_table_without_s3_policy(self):
        """Test that web bounces table creation works without S3 storage policy."""
        with patch.dict(os.environ, {}, clear=True):
            sql = WEB_BOUNCES_DAILY_SQL(table_name="web_bounces_test_default")

            # Verify the table name is correct
            assert "web_bounces_test_default" in sql

            # Verify no storage policy is mentioned
            assert "storage_policy" not in sql

            # Verify it's still a ReplicatedMergeTree
            assert "ReplicatedMergeTree" in sql

    def test_storage_policy_differences(self):
        """Test that S3 and non-S3 tables differ only in storage policy settings."""
        with patch.dict(os.environ, {}, clear=True):
            default_sql = WEB_STATS_DAILY_SQL(table_name="test_table")

        with patch.dict(os.environ, {"WEB_ANALYTICS_STORAGE_POLICY": "s3"}):
            s3_sql = WEB_STATS_DAILY_SQL(table_name="test_table")

        # Both should have the same table name
        assert "test_table" in default_sql
        assert "test_table" in s3_sql

        # Both should use ReplicatedMergeTree
        assert "ReplicatedMergeTree" in default_sql
        assert "ReplicatedMergeTree" in s3_sql

        # Only S3 should have storage policy
        assert "storage_policy" not in default_sql
        assert "SETTINGS storage_policy = 's3_policy'" in s3_sql

        # Both should have the same column structure
        assert "period_bucket DateTime" in default_sql
        assert "period_bucket DateTime" in s3_sql
        assert "team_id UInt64" in default_sql
        assert "team_id UInt64" in s3_sql
