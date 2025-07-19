import pytest
from posthog.models.web_preaggregated.sql import (
    DROP_PARTITION_SQL,
    TABLE_TEMPLATE,
    HOURLY_TABLE_TEMPLATE,
    WEB_STATS_COLUMNS,
    WEB_STATS_ORDER_BY_FUNC,
)


class TestPartitionDropSQL:
    def test_drop_partition_daily_format(self):
        sql = DROP_PARTITION_SQL("web_stats_daily", "2024-01-15")

        expected = """
    ALTER TABLE web_stats_daily
    DROP PARTITION '20240115'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_daily_default_no_cluster(self):
        sql = DROP_PARTITION_SQL("web_stats_daily", "2024-01-15")

        expected = """
    ALTER TABLE web_stats_daily
    DROP PARTITION '20240115'
    """
        assert sql.strip() == expected.strip()
        assert "ON CLUSTER" not in sql

    def test_drop_partition_hourly_with_hour(self):
        sql = DROP_PARTITION_SQL("web_stats_hourly", "2024-01-15 14", granularity="hourly")

        expected = """
    ALTER TABLE web_stats_hourly
    DROP PARTITION '2024011514'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_hourly_without_hour(self):
        sql = DROP_PARTITION_SQL("web_stats_hourly", "2024-01-15", granularity="hourly")

        expected = """
    ALTER TABLE web_stats_hourly
    DROP PARTITION '2024011500'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_hourly_single_digit_hour(self):
        sql = DROP_PARTITION_SQL("web_stats_hourly", "2024-01-15 5", granularity="hourly")

        expected = """
    ALTER TABLE web_stats_hourly
    DROP PARTITION '2024011505'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_daily_different_table(self):
        sql = DROP_PARTITION_SQL("web_bounces_daily", "2024-01-15")

        expected = """
    ALTER TABLE web_bounces_daily
    DROP PARTITION '20240115'
    """
        assert sql.strip() == expected.strip()

    def test_drop_partition_hourly_different_table(self):
        sql = DROP_PARTITION_SQL("web_bounces_hourly", "2024-01-15 08", granularity="hourly")

        expected = """
    ALTER TABLE web_bounces_hourly
    DROP PARTITION '2024011508'
    """
        assert sql.strip() == expected.strip()


class TestTableTemplates:
    def test_daily_table_partition_by_date(self):
        sql = TABLE_TEMPLATE("web_stats_daily", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC())

        assert "PARTITION BY toYYYYMMDD(period_bucket)" in sql
        assert "web_stats_daily" in sql

    def test_hourly_table_partition_by_hour(self):
        sql = HOURLY_TABLE_TEMPLATE("web_stats_hourly", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC())

        assert "PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')" in sql
        assert "web_stats_hourly" in sql

    def test_hourly_table_with_ttl(self):
        sql = HOURLY_TABLE_TEMPLATE("web_stats_hourly", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC(), ttl="24 HOUR")

        assert "PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')" in sql
        assert "TTL period_bucket + INTERVAL 24 HOUR DELETE" in sql


class TestPartitionIDFormatting:
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
        sql = DROP_PARTITION_SQL("test_table", date_input, granularity=granularity)
        assert f"'{expected_partition}'" in sql

    def test_invalid_hourly_format_defaults_to_00(self):
        sql = DROP_PARTITION_SQL("test_table", "2024-01-15", granularity="hourly")
        assert "'2024011500'" in sql


class TestHourlyPartitioningIntegration:
    def test_hourly_partition_drop_for_different_hours(self):
        test_cases = [
            ("2024-01-15 00", "2024011500"),
            ("2024-01-15 01", "2024011501"),
            ("2024-01-15 12", "2024011512"),
            ("2024-01-15 23", "2024011523"),
        ]

        for date_input, expected_partition in test_cases:
            sql = DROP_PARTITION_SQL("web_stats_hourly", date_input, granularity="hourly")
            assert f"'{expected_partition}'" in sql

    def test_hourly_table_creation_with_ttl(self):
        sql = HOURLY_TABLE_TEMPLATE("web_stats_hourly", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC(), ttl="24 HOUR")

        assert "PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')" in sql
        assert "TTL period_bucket + INTERVAL 24 HOUR DELETE" in sql
        assert "ReplicatedMergeTree" in sql

    def test_hourly_vs_daily_partition_difference(self):
        date = "2024-01-15"

        daily_sql = DROP_PARTITION_SQL("web_stats_daily", date, granularity="daily")
        hourly_sql = DROP_PARTITION_SQL("web_stats_hourly", date, granularity="hourly")

        # Daily should be YYYYMMDD format
        assert "'20240115'" in daily_sql
        # Hourly should be YYYYMMDDHH format (defaulting to 00)
        assert "'2024011500'" in hourly_sql

    def test_multi_day_partition_scenario_daily(self):
        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]

        for date in dates:
            sql = DROP_PARTITION_SQL("web_stats_daily", date, granularity="daily")
            expected_partition = date.replace("-", "")
            assert f"'{expected_partition}'" in sql
            assert "ALTER TABLE web_stats_daily" in sql
            assert "DROP PARTITION" in sql

    def test_month_boundary_partitions(self):
        test_cases = [
            ("2024-01-31", "daily", "20240131"),
            ("2024-02-01", "daily", "20240201"),
            ("2024-02-29", "daily", "20240229"),  # Leap year
            ("2024-03-01", "daily", "20240301"),
        ]

        for date, granularity, expected_partition in test_cases:
            sql = DROP_PARTITION_SQL("web_stats_daily", date, granularity=granularity)
            assert f"'{expected_partition}'" in sql

    def test_year_boundary_partitions(self):
        test_cases = [
            ("2023-12-31", "daily", "20231231"),
            ("2024-01-01", "daily", "20240101"),
        ]

        for date, granularity, expected_partition in test_cases:
            sql = DROP_PARTITION_SQL("web_stats_daily", date, granularity=granularity)
            assert f"'{expected_partition}'" in sql

    def test_granularity_parameter_is_case_sensitive_and_invalid_defaults_to_daily(self):
        date = "2024-01-15"

        # Test valid granularities
        daily_sql = DROP_PARTITION_SQL("test_table", date, granularity="daily")
        hourly_sql = DROP_PARTITION_SQL("test_table", date, granularity="hourly")

        assert "'20240115'" in daily_sql
        assert "'2024011500'" in hourly_sql

        # Test that invalid granularity defaults to daily behavior
        # (This tests the else clause in the function)
        invalid_sql = DROP_PARTITION_SQL("test_table", date, granularity="invalid")
        assert "'20240115'" in invalid_sql
