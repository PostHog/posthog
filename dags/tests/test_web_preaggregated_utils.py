from dags.web_preaggregated_utils import (
    TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
    CLICKHOUSE_SETTINGS,
    format_clickhouse_settings,
    merge_clickhouse_settings,
    WEB_ANALYTICS_CONFIG_SCHEMA,
)


class TestWebAnalyticsUtilities:
    def test_format_clickhouse_settings(self):
        settings = {
            "max_execution_time": "1200",
            "max_memory_usage": "50000000000",
            "max_threads": "8",
        }

        result = format_clickhouse_settings(settings)
        expected = "max_execution_time=1200,max_memory_usage=50000000000,max_threads=8"
        assert result == expected

    def test_merge_clickhouse_settings(self):
        base_settings = {
            "max_execution_time": "1200",
            "max_memory_usage": "50000000000",
        }

        extra_settings = "max_threads=16,join_algorithm=parallel_hash"
        result = merge_clickhouse_settings(base_settings, extra_settings)

        expected_parts = [
            "max_execution_time=1200",
            "max_memory_usage=50000000000",
            "max_threads=16",
            "join_algorithm=parallel_hash",
        ]

        for part in expected_parts:
            assert part in result

    def test_merge_clickhouse_settings_empty_extra(self):
        base_settings = {"max_execution_time": "1200"}

        for empty_extra in ["", None]:
            result = merge_clickhouse_settings(base_settings, empty_extra)
            assert result == "max_execution_time=1200"

    def test_merge_clickhouse_settings_override(self):
        base_settings = {"max_execution_time": "1200"}
        extra_settings = "max_execution_time=1800"

        result = merge_clickhouse_settings(base_settings, extra_settings)
        assert result == "max_execution_time=1800"


class TestClickHouseSettings:
    def test_daily_clickhouse_settings_values(self):
        expected_settings = [
            "max_execution_time",
            "max_bytes_before_external_group_by",
            "max_memory_usage",
            "distributed_aggregation_memory_efficient",
        ]

        for setting in expected_settings:
            assert setting in CLICKHOUSE_SETTINGS

        # Test that timeout is reasonable
        timeout = int(CLICKHOUSE_SETTINGS["max_execution_time"])
        assert 300 <= timeout <= 3600  # Between 5 minutes and 1 hour

        # Test that memory limits are set to reasonable values
        memory_limit = int(CLICKHOUSE_SETTINGS["max_memory_usage"])
        assert 1024 * 1024 * 1024 < memory_limit <= 150 * 1024 * 1024 * 1024  # Between 1GB and 150GB

        # Test that distributed aggregation is enabled for efficiency
        assert CLICKHOUSE_SETTINGS["distributed_aggregation_memory_efficient"] == "1"


class TestConfigSchemas:
    def test_daily_config_schema(self):
        required_fields = ["team_ids", "extra_clickhouse_settings"]

        for field in required_fields:
            assert field in WEB_ANALYTICS_CONFIG_SCHEMA

        assert WEB_ANALYTICS_CONFIG_SCHEMA["team_ids"].default_value == TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED
        assert WEB_ANALYTICS_CONFIG_SCHEMA["extra_clickhouse_settings"].default_value == ""
