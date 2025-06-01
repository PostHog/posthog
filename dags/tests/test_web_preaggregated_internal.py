import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from unittest.mock import patch, Mock

import dagster
import pytest

from dags.web_preaggregated_internal import (
    web_analytics_preaggregated_tables,
    web_bounces_daily,
    web_stats_daily,
    pre_aggregate_web_analytics_data,
    format_clickhouse_settings,
    merge_clickhouse_settings,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    WEB_ANALYTICS_CONCURRENCY_KEYS,
    get_concurrency_config_example,
)
from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
    DISTRIBUTED_WEB_STATS_DAILY_SQL,
    DISTRIBUTED_WEB_BOUNCES_DAILY_SQL,
)


@dataclass
class WebAnalyticsTestData:
    """Test data structure for web analytics tests."""
    team_id: int
    session_id: str
    person_id: UUID
    event: str
    timestamp: datetime
    properties: dict
    expected_in_stats: bool = True
    expected_in_bounces: bool = True


def create_pageview_event(
    team_id: int = 1,
    timestamp: datetime = None,
    session_id: str = None,
    person_id: UUID = None,
    pathname: str = "/home",
    utm_source: str = "google",
    host: str = "example.com",
    device_type: str = "Desktop",
    browser: str = "Chrome",
    country_code: str = "US",
    **extra_properties
) -> WebAnalyticsTestData:
    return WebAnalyticsTestData(
        team_id=team_id,
        session_id=session_id or str(uuid4()),
        person_id=person_id or uuid4(),
        event="$pageview",
        timestamp=timestamp or datetime.now(),
        properties={
            "$pathname": pathname,
            "$host": host,
            "$device_type": device_type,
            "$browser": browser,
            "$geoip_country_code": country_code,
            "$session_id": session_id or str(uuid4()),
            **extra_properties,
        },
    )


class TestWebAnalyticsHelpers:
    """Test helper functions for web analytics configuration."""

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
        
        # Should contain all settings
        assert "max_execution_time=1200" in result
        assert "max_memory_usage=50000000000" in result
        assert "max_threads=16" in result
        assert "join_algorithm=parallel_hash" in result

    def test_merge_clickhouse_settings_empty_extra(self):
        base_settings = {"max_execution_time": "1200"}
        
        result = merge_clickhouse_settings(base_settings, "")
        assert result == "max_execution_time=1200"
        
        result = merge_clickhouse_settings(base_settings, None)
        assert result == "max_execution_time=1200"

    def test_merge_clickhouse_settings_override(self):
        base_settings = {"max_execution_time": "1200"}
        extra_settings = "max_execution_time=1800"
        
        result = merge_clickhouse_settings(base_settings, extra_settings)
        assert result == "max_execution_time=1800"


class TestWebAnalyticsPreAggregation:
    """Test web analytics pre-aggregation functionality."""

    @patch('dags.web_preaggregated_internal.sync_execute')
    def test_pre_aggregate_web_analytics_data_with_partition(self, mock_sync_execute):
        """Test pre-aggregation with a specific partition date."""
        # Mock context
        context = Mock()
        context.op_config = {
            "team_ids": [1, 2],
            "extra_clickhouse_settings": "max_threads=4",
            "use_high_performance_settings": False,
        }
        
        # Mock SQL generator
        def mock_sql_generator(date_start, date_end, team_ids, settings, table_name):
            return f"INSERT INTO {table_name} SELECT * FROM events WHERE date >= '{date_start}' AND date < '{date_end}'"
        
        # Call function
        pre_aggregate_web_analytics_data(
            context=context,
            table_name="web_stats_daily",
            sql_generator=mock_sql_generator,
            partition_date="2023-01-01",
        )
        
        # Verify sync_execute was called
        mock_sync_execute.assert_called_once()
        
        # Get the call arguments
        call_args = mock_sync_execute.call_args[0][0]
        assert "INSERT INTO web_stats_daily" in call_args
        assert "date >= '2023-01-01'" in call_args
        assert "date < '2023-01-02'" in call_args

    @patch('dags.web_preaggregated_internal.sync_execute')
    def test_pre_aggregate_web_analytics_data_no_partition(self, mock_sync_execute):
        """Test pre-aggregation without partition (full history)."""
        context = Mock()
        context.op_config = {
            "team_ids": [],
            "extra_clickhouse_settings": "",
            "use_high_performance_settings": True,
        }
        
        def mock_sql_generator(date_start, date_end, team_ids, settings, table_name):
            return f"INSERT INTO {table_name} SELECT * FROM events WHERE date >= '{date_start}' AND date < '{date_end}'"
        
        pre_aggregate_web_analytics_data(
            context=context,
            table_name="web_bounces_daily",
            sql_generator=mock_sql_generator,
            partition_date=None,
        )
        
        mock_sync_execute.assert_called_once()
        call_args = mock_sync_execute.call_args[0][0]
        assert "INSERT INTO web_bounces_daily" in call_args
        assert "date >= '2020-01-01'" in call_args

    def test_pre_aggregate_web_analytics_data_invalid_date(self):
        """Test pre-aggregation with invalid partition date."""
        context = Mock()
        context.op_config = {}
        
        def mock_sql_generator(date_start, date_end, team_ids, settings, table_name):
            return "SELECT 1"
        
        with pytest.raises(dagster.Failure, match="Invalid partition date format"):
            pre_aggregate_web_analytics_data(
                context=context,
                table_name="web_stats_daily",
                sql_generator=mock_sql_generator,
                partition_date="invalid-date",
            )

    @patch('dags.web_preaggregated_internal.sync_execute')
    def test_pre_aggregate_web_analytics_data_sql_error(self, mock_sync_execute):
        """Test pre-aggregation with SQL execution error."""
        mock_sync_execute.side_effect = Exception("ClickHouse connection error")
        
        context = Mock()
        context.op_config = {}
        
        def mock_sql_generator(date_start, date_end, team_ids, settings, table_name):
            return "SELECT 1"
        
        with pytest.raises(dagster.Failure, match="Failed to pre-aggregate"):
            pre_aggregate_web_analytics_data(
                context=context,
                table_name="web_stats_daily",
                sql_generator=mock_sql_generator,
                partition_date="2023-01-01",
            )


def test_web_analytics_table_creation(cluster: ClickhouseCluster) -> None:
    """Test that web analytics pre-aggregated tables can be created successfully."""
    
    # Create a mock Dagster resource
    mock_cluster_resource = Mock()
    mock_cluster_resource.value = cluster
    
    # Call the asset function
    result = web_analytics_preaggregated_tables(cluster=mock_cluster_resource)
    
    assert result is True
    
    # Verify tables exist
    stats_table_result = cluster.any_host(Query("SHOW TABLES LIKE 'web_stats_daily'")).result()
    assert len(stats_table_result) > 0
    
    bounces_table_result = cluster.any_host(Query("SHOW TABLES LIKE 'web_bounces_daily'")).result()
    assert len(bounces_table_result) > 0
    
    # Verify table structure
    stats_columns = cluster.any_host(Query("DESCRIBE TABLE web_stats_daily")).result()
    stats_column_names = [col[0] for col in stats_columns]
    
    # Check for essential columns
    assert "day_bucket" in stats_column_names
    assert "team_id" in stats_column_names
    assert "pathname" in stats_column_names
    assert "persons_uniq_state" in stats_column_names
    assert "sessions_uniq_state" in stats_column_names
    assert "pageviews_count_state" in stats_column_names
    assert "updated_at" in stats_column_names
    
    bounces_columns = cluster.any_host(Query("DESCRIBE TABLE web_bounces_daily")).result()
    bounces_column_names = [col[0] for col in bounces_columns]
    
    # Check for essential columns including bounce-specific ones
    assert "day_bucket" in bounces_column_names
    assert "team_id" in bounces_column_names
    assert "bounces_count_state" in bounces_column_names
    assert "total_session_duration_state" in bounces_column_names


def test_web_analytics_data_aggregation(cluster: ClickhouseCluster) -> None:
    """Test end-to-end web analytics data aggregation."""
    start_date = datetime(2023, 1, 1)
    
    # Create test data
    test_events = [
        # Team 1 events on 2023-01-01
        create_pageview_event(
            team_id=1,
            timestamp=start_date + timedelta(hours=1),
            pathname="/home",
            utm_source="google",
            session_id="session1",
            person_id=UUID(int=1),
        ),
        create_pageview_event(
            team_id=1,
            timestamp=start_date + timedelta(hours=2),
            pathname="/about",
            utm_source="google",
            session_id="session1",
            person_id=UUID(int=1),
        ),
        # Team 2 events on 2023-01-01
        create_pageview_event(
            team_id=2,
            timestamp=start_date + timedelta(hours=3),
            pathname="/pricing",
            utm_source="twitter",
            session_id="session2",
            person_id=UUID(int=2),
        ),
        # Team 1 events on 2023-01-02 (should be excluded)
        create_pageview_event(
            team_id=1,
            timestamp=start_date + timedelta(days=1, hours=1),
            pathname="/contact",
            utm_source="direct",
            session_id="session3",
            person_id=UUID(int=3),
        ),
    ]
    
    # Insert test events
    event_values = []
    for event_data in test_events:
        event_values.append((
            uuid4(),  # event uuid
            event_data.team_id,
            event_data.event,
            event_data.timestamp,
            json.dumps(event_data.properties),
            event_data.person_id,
            event_data.session_id,
        ))
    
    cluster.any_host(
        Query(
            "INSERT INTO events (uuid, team_id, event, timestamp, properties, person_id, `$session_id`) VALUES",
            event_values,
        )
    ).result()
    
    # Insert corresponding raw_sessions data
    session_values = []
    for i, event_data in enumerate(test_events):
        if event_data.session_id not in [s[1] for s in session_values]:  # Avoid duplicates
            session_values.append((
                event_data.team_id,
                event_data.session_id,
                event_data.timestamp,
                event_data.timestamp + timedelta(minutes=30),
                1,  # page_screen_autocapture_uniq_up_to
                event_data.properties.get("$pathname", "/"),
                event_data.properties.get("$pathname", "/"),
                event_data.properties.get("utm_source", ""),
                "",  # initial_utm_medium
                "",  # initial_utm_campaign
                "",  # initial_utm_term
                "",  # initial_utm_content
                event_data.properties.get("$geoip_country_code", ""),
                "",  # initial_geoip_subdivision_1_code
                "",  # initial_geoip_subdivision_1_name
                "",  # initial_geoip_subdivision_city_name
                "",  # initial_geoip_time_zone
            ))
    
    cluster.any_host(
        Query(
            """INSERT INTO raw_sessions 
            (team_id, session_id_v7, min_timestamp, max_timestamp, page_screen_autocapture_uniq_up_to,
             entry_url, end_url, initial_utm_source, initial_utm_medium, initial_utm_campaign,
             initial_utm_term, initial_utm_content, initial_geoip_country_code,
             initial_geoip_subdivision_1_code, initial_geoip_subdivision_1_name,
             initial_geoip_subdivision_city_name, initial_geoip_time_zone) VALUES""",
            session_values,
        )
    ).result()
    
    # Setup tables
    web_analytics_preaggregated_tables(cluster=Mock(value=cluster))
    
    # Create mock context for testing
    mock_context = Mock()
    mock_context.op_config = {"team_ids": [1, 2], "extra_clickhouse_settings": "", "use_high_performance_settings": False}
    mock_context.has_partition_key = True
    mock_context.partition_key = "2023-01-01"
    
    # Run aggregation for stats
    web_stats_daily(context=mock_context)
    
    # Run aggregation for bounces  
    web_bounces_daily(context=mock_context)
    
    # Verify web_stats_daily results
    stats_results = cluster.any_host(
        Query(
            """
            SELECT team_id, pathname, utm_source, 
                   uniqMerge(persons_uniq_state) as unique_persons,
                   uniqMerge(sessions_uniq_state) as unique_sessions,
                   sumMerge(pageviews_count_state) as total_pageviews
            FROM web_stats_daily 
            WHERE day_bucket = '2023-01-01'
            ORDER BY team_id, pathname
            """
        )
    ).result()
    
    # Should have aggregated data for both teams
    assert len(stats_results) >= 2  # At least one row per unique pathname/team combination
    
    # Verify some basic aggregation
    team_1_results = [r for r in stats_results if r[0] == 1]
    team_2_results = [r for r in stats_results if r[0] == 2]
    
    assert len(team_1_results) >= 1
    assert len(team_2_results) >= 1
    
    # Verify bounces data exists
    bounces_results = cluster.any_host(
        Query(
            """
            SELECT team_id, 
                   uniqMerge(persons_uniq_state) as unique_persons,
                   uniqMerge(sessions_uniq_state) as unique_sessions,
                   sumMerge(pageviews_count_state) as total_pageviews,
                   sumMerge(bounces_count_state) as total_bounces
            FROM web_bounces_daily 
            WHERE day_bucket = '2023-01-01'
            GROUP BY team_id
            ORDER BY team_id
            """
        )
    ).result()
    
    assert len(bounces_results) >= 2  # Should have data for both teams


def test_web_analytics_config_schema():
    """Test that the web analytics config schema is properly defined."""
    assert "team_ids" in WEB_ANALYTICS_CONFIG_SCHEMA
    assert "extra_clickhouse_settings" in WEB_ANALYTICS_CONFIG_SCHEMA
    assert "use_high_performance_settings" in WEB_ANALYTICS_CONFIG_SCHEMA
    
    # Check default values
    assert WEB_ANALYTICS_CONFIG_SCHEMA["team_ids"].default_value == []
    assert WEB_ANALYTICS_CONFIG_SCHEMA["extra_clickhouse_settings"].default_value == ""
    assert WEB_ANALYTICS_CONFIG_SCHEMA["use_high_performance_settings"].default_value is False


def test_concurrency_limits_configuration():
    """Test that concurrency keys are properly configured."""
    # Check that all expected concurrency keys are defined
    expected_keys = [
        "bounces_heavy_query",
        "stats_heavy_query", 
        "table_setup"
    ]
    
    for key in expected_keys:
        assert key in WEB_ANALYTICS_CONCURRENCY_KEYS
        assert WEB_ANALYTICS_CONCURRENCY_KEYS[key].startswith("web_analytics_")
    
    # Check specific key mappings
    assert WEB_ANALYTICS_CONCURRENCY_KEYS["bounces_heavy_query"] == "web_analytics_bounces_heavy_query"
    assert WEB_ANALYTICS_CONCURRENCY_KEYS["stats_heavy_query"] == "web_analytics_stats_heavy_query"
    assert WEB_ANALYTICS_CONCURRENCY_KEYS["table_setup"] == "web_analytics_table_setup"
    
    # Verify config example is available
    config_example = get_concurrency_config_example()
    assert "run_coordinator" in config_example
    assert "concurrency_limits" in config_example


def test_asset_concurrency_tags():
    """Test that assets have proper concurrency tags configured."""
    bounces_key = "web_analytics_bounces_heavy_query"
    stats_key = "web_analytics_stats_heavy_query"
    table_setup_key = "web_analytics_table_setup"
    
    # Check that the keys exist in the concurrency keys mapping
    assert bounces_key in WEB_ANALYTICS_CONCURRENCY_KEYS.values()
    assert stats_key in WEB_ANALYTICS_CONCURRENCY_KEYS.values()
    assert table_setup_key in WEB_ANALYTICS_CONCURRENCY_KEYS.values()


def test_sql_generation():
    """Test that SQL generation functions work correctly."""
    # Test WEB_STATS_DAILY_SQL
    stats_sql = WEB_STATS_DAILY_SQL(table_name="test_web_stats", on_cluster=False)
    assert "CREATE TABLE IF NOT EXISTS test_web_stats" in stats_sql
    assert "ReplacingMergeTree" in stats_sql
    assert "persons_uniq_state AggregateFunction(uniq, UUID)" in stats_sql
    
    # Test WEB_BOUNCES_DAILY_SQL  
    bounces_sql = WEB_BOUNCES_DAILY_SQL(table_name="test_web_bounces", on_cluster=False)
    assert "CREATE TABLE IF NOT EXISTS test_web_bounces" in bounces_sql
    assert "ReplacingMergeTree" in bounces_sql
    assert "bounces_count_state AggregateFunction(sum, UInt64)" in bounces_sql
    assert "total_session_duration_state AggregateFunction(sum, Int64)" in bounces_sql
    
    # Test distributed table SQL
    dist_stats_sql = DISTRIBUTED_WEB_STATS_DAILY_SQL()
    assert "CREATE TABLE IF NOT EXISTS web_stats_daily_distributed" in dist_stats_sql
    assert "Distributed" in dist_stats_sql
    
    dist_bounces_sql = DISTRIBUTED_WEB_BOUNCES_DAILY_SQL()
    assert "CREATE TABLE IF NOT EXISTS web_bounces_daily_distributed" in dist_bounces_sql
    assert "Distributed" in dist_bounces_sql 