import pytest
import dagster
import structlog

from datetime import datetime, UTC
from unittest.mock import patch
from freezegun import freeze_time

from posthog.test.base import (
    ClickhouseTestMixin,
    APIBaseTest,
    _create_event,
    _create_person,
    flush_persons_and_events,
    cleanup_materialized_columns,
)
from posthog.clickhouse.client import sync_execute
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_INSERT_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
)
from posthog.models.utils import uuid7
from ee.clickhouse.materialized_columns.columns import materialize
from dags.web_preaggregated_daily import pre_aggregate_web_analytics_data

logger = structlog.get_logger(__name__)


@pytest.mark.django_db
class TestWebPreAggregatedDagsterIntegration(ClickhouseTestMixin, APIBaseTest):
    # Columns that need to be materialized for web analytics pre-aggregated queries to work
    MATERIALIZED_COLUMNS = [
        "$host",
        "$device_type",
        "$browser",
        "$os",
        "$viewport_width",
        "$viewport_height",
        "$geoip_country_code",
        "$geoip_city_name",
        "$geoip_subdivision_1_code",
        "$pathname",
    ]

    def setUp(self):
        super().setUp()

        self._materialize_required_columns()
        self._create_test_tables()
        self._create_test_events_across_periods()

    def tearDown(self):
        cleanup_materialized_columns()
        super().tearDown()

    def _materialize_required_columns(self):
        logger.info("Materializing required columns for web analytics")
        for column in self.MATERIALIZED_COLUMNS:
            materialize("events", column)

    def _create_test_tables(self):
        logger.info("Creating test tables for web analytics pre-aggregation")
        sync_execute(WEB_STATS_DAILY_SQL(table_name="test_web_stats_daily", on_cluster=False))
        sync_execute(WEB_BOUNCES_DAILY_SQL(table_name="test_web_bounces_daily", on_cluster=False))

        logger.info("Test tables created successfully")

    def _create_test_events_across_periods(self):
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])
        _create_person(team_id=self.team.pk, distinct_ids=["user2"])
        _create_person(team_id=self.team.pk, distinct_ids=["user3"])

        # Event on 2024-01-15 (period 1)
        with freeze_time("2024-01-15T10:00:00Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user1",
                timestamp="2024-01-15T10:00:00Z",
                properties={
                    "$session_id": str(uuid7()),
                    "$current_url": "https://example.com/page1",
                    "$pathname": "/page1",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Linux",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "San Francisco",
                    "$geoip_subdivision_1_code": "CA",
                },
            )

        # Another event same day different user
        with freeze_time("2024-01-15T11:00:00Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user2",
                timestamp="2024-01-15T11:00:00Z",
                properties={
                    "$session_id": str(uuid7()),
                    "$current_url": "https://example.com/page2",
                    "$pathname": "/page2",
                    "$host": "example.com",
                    "$device_type": "Mobile",
                    "$browser": "Safari",
                    "$os": "iOS",
                    "$viewport_width": 375,
                    "$viewport_height": 812,
                    "$geoip_country_code": "CA",
                    "$geoip_city_name": "Toronto",
                    "$geoip_subdivision_1_code": "ON",
                },
            )

        # Event on 2024-01-16 (period 2)
        with freeze_time("2024-01-16T10:00:00Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user1",
                timestamp="2024-01-16T10:00:00Z",
                properties={
                    "$session_id": str(uuid7()),
                    "$current_url": "https://example.com/page3",
                    "$pathname": "/page3",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Linux",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "San Francisco",
                    "$geoip_subdivision_1_code": "CA",
                },
            )

        # Another event same day 2024-01-16
        with freeze_time("2024-01-16T11:00:00Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user3",
                timestamp="2024-01-16T11:00:00Z",
                properties={
                    "$session_id": str(uuid7()),
                    "$current_url": "https://example.com/page4",
                    "$pathname": "/page4",
                    "$host": "example.com",
                    "$device_type": "Tablet",
                    "$browser": "Firefox",
                    "$os": "Android",
                    "$viewport_width": 768,
                    "$viewport_height": 1024,
                    "$geoip_country_code": "GB",
                    "$geoip_city_name": "London",
                    "$geoip_subdivision_1_code": "ENG",
                },
            )

        # Event on 2024-01-17 (period 3)
        with freeze_time("2024-01-17T10:00:00Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user2",
                timestamp="2024-01-17T10:00:00Z",
                properties={
                    "$session_id": str(uuid7()),
                    "$current_url": "https://example.com/page5",
                    "$pathname": "/page5",
                    "$host": "example.com",
                    "$device_type": "Mobile",
                    "$browser": "Safari",
                    "$os": "iOS",
                    "$viewport_width": 375,
                    "$viewport_height": 812,
                    "$geoip_country_code": "CA",
                    "$geoip_city_name": "Toronto",
                    "$geoip_subdivision_1_code": "ON",
                },
            )

        flush_persons_and_events()

    def _create_dagster_context(self, date_start: str, date_end: str):
        # Create base context with partition key to get logging and other functionality
        base_context = dagster.build_asset_context(partition_key=date_start)

        class TestContext:
            def __init__(self, base_context, team_id):
                self.log = base_context.log
                self.partition_key = base_context.partition_key
                self.op_config = {"team_ids": [team_id], "extra_clickhouse_settings": "max_execution_time=300"}

                start_dt = datetime.fromisoformat(date_start).replace(tzinfo=UTC)
                end_dt = datetime.fromisoformat(date_end).replace(tzinfo=UTC)
                self.partition_time_window = (start_dt, end_dt)

        return TestContext(base_context, self.team.pk)

    def _get_partition_data_count(self, table_name: str, partition_id: str) -> int:
        query = f"""
        SELECT count()
        FROM {table_name}
        WHERE toYYYYMMDD(period_bucket) = '{partition_id}'
        """
        result = sync_execute(query)
        return result[0][0] if result else 0

    def _partition_exists(self, table_name: str, partition_id: str) -> bool:
        query = f"""
        SELECT count()
        FROM system.parts
        WHERE database = currentDatabase()
        AND table = '{table_name}'
        AND partition = '{partition_id}'
        AND active = 1
        """
        result = sync_execute(query)
        return result[0][0] > 0 if result else False

    def test_web_stats_single_period_aggregation(self):
        context = self._create_dagster_context("2024-01-15", "2024-01-16")

        pre_aggregate_web_analytics_data(
            context=context, table_name="test_web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
        )

        count = self._get_partition_data_count("test_web_stats_daily", "20240115")

        assert count > 0
        assert self._partition_exists("test_web_stats_daily", "20240115")

    def test_web_bounces_single_period_aggregation(self):
        context = self._create_dagster_context("2024-01-16", "2024-01-17")

        pre_aggregate_web_analytics_data(
            context=context, table_name="test_web_bounces_daily", sql_generator=WEB_BOUNCES_INSERT_SQL
        )

        count = self._get_partition_data_count("test_web_bounces_daily", "20240116")
        assert count > 0
        assert self._partition_exists("test_web_bounces_daily", "20240116")

    def test_partition_drop_idempotency(self):
        context = self._create_dagster_context("2024-01-15", "2024-01-16")

        pre_aggregate_web_analytics_data(
            context=context, table_name="test_web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
        )

        first_run_count = self._get_partition_data_count("test_web_stats_daily", "20240115")
        assert first_run_count > 0

        pre_aggregate_web_analytics_data(
            context=context, table_name="test_web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
        )

        second_run_count = self._get_partition_data_count("test_web_stats_daily", "20240115")
        assert second_run_count == first_run_count

        pre_aggregate_web_analytics_data(
            context=context, table_name="test_web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
        )

        third_run_count = self._get_partition_data_count("test_web_stats_daily", "20240115")
        assert third_run_count == first_run_count

    def test_multiple_periods_aggregation(self):
        periods = [
            ("2024-01-15", "2024-01-16", "20240115"),
            ("2024-01-16", "2024-01-17", "20240116"),
            ("2024-01-17", "2024-01-18", "20240117"),
        ]

        partition_counts = {}

        for date_start, date_end, partition_id in periods:
            context = self._create_dagster_context(date_start, date_end)

            pre_aggregate_web_analytics_data(
                context=context, table_name="test_web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
            )

            count = self._get_partition_data_count("test_web_stats_daily", partition_id)
            partition_counts[partition_id] = count

            assert self._partition_exists("test_web_stats_daily", partition_id)
            assert count > 0

        assert len(partition_counts) == 3, "Should have 3 partitions"
        assert all(count > 0 for count in partition_counts.values()), "All partitions should have data"

    def test_partition_drop_with_data_modification(self):
        context = self._create_dagster_context("2024-01-15", "2024-01-16")

        pre_aggregate_web_analytics_data(
            context=context, table_name="test_web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
        )

        original_count = self._get_partition_data_count("test_web_stats_daily", "20240115")
        assert original_count > 0

        with freeze_time("2024-01-15T15:00:00Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user3",
                timestamp="2024-01-15T15:00:00Z",
                properties={
                    "$session_id": str(uuid7()),
                    "$current_url": "https://example.com/new_page",
                    "$pathname": "/new_page",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Linux",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "San Francisco",
                    "$geoip_subdivision_1_code": "CA",
                },
            )

        flush_persons_and_events()

        # Second run with additional data
        pre_aggregate_web_analytics_data(
            context=context, table_name="test_web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
        )

        updated_count = self._get_partition_data_count("test_web_stats_daily", "20240115")

        # The count might be different due to additional source data, but should be consistent
        # The key is that it's not doubled (which would happen without partition dropping)
        assert updated_count >= original_count, "Updated count should be at least as much as original"

        # Run again to verify idempotency with the new data
        pre_aggregate_web_analytics_data(
            context=context, table_name="test_web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
        )

        final_count = self._get_partition_data_count("test_web_stats_daily", "20240115")
        assert final_count == updated_count

    @patch("dags.web_preaggregated_daily.sync_execute")
    def test_partition_drop_sql_generation(self, mock_sync_execute):
        context = self._create_dagster_context("2024-01-15", "2024-01-16")

        pre_aggregate_web_analytics_data(
            context=context, table_name="test_web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
        )

        assert mock_sync_execute.call_count == 2

        first_call_sql = mock_sync_execute.call_args_list[0][0][0]
        assert "DROP PARTITION" in first_call_sql
        assert "20240115" in first_call_sql

        second_call_sql = mock_sync_execute.call_args_list[1][0][0]
        assert "INSERT INTO" in second_call_sql
        assert "test_web_stats_daily" in second_call_sql

    def test_dagster_context_and_partition_logic(self):
        context = self._create_dagster_context("2024-01-15", "2024-01-16")

        # Verify context has expected properties
        assert hasattr(context, "op_config")
        assert hasattr(context, "partition_time_window")
        assert hasattr(context, "log")

        # Test partition time window
        start_dt, end_dt = context.partition_time_window
        assert start_dt.strftime("%Y-%m-%d") == "2024-01-15"
        assert end_dt.strftime("%Y-%m-%d") == "2024-01-16"

        # Test partition ID generation (matches our DAG logic)
        date_start = start_dt.strftime("%Y-%m-%d")
        partition_id = date_start.replace("-", "")  # Convert 2024-01-15 to 20240115
        assert partition_id == "20240115"

        # Test team_ids from config
        team_ids = context.op_config.get("team_ids", [])
        assert self.team.pk in team_ids
