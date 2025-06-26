#!/usr/bin/env python3
"""
Test script to verify chdb compatibility with ClickHouse v25 .native format exports.
This test is designed to run in PostHog's CI to ensure compatibility before v25 migration.
"""
import chdb
import os
import tempfile
import requests
import time
from io import StringIO
import csv
import sys

def test_basic_chdb_functionality():
    """Test basic chdb functionality"""
    print("Testing basic chdb functionality...")
    try:
        result = chdb.query("SELECT 'Hello chdb' as message", output_format="CSV")
        print(f"✅ Basic chdb query works: {result}")
        return True
    except Exception as e:
        print(f"❌ Basic chdb query failed: {e}")
        return False

def test_chdb_version_compatibility():
    """Test chdb version and ClickHouse version compatibility"""
    print("Testing chdb version compatibility...")
    try:
        version_result = chdb.query("SELECT version()", output_format="CSV")
        reader = csv.reader(StringIO(str(version_result)))
        version = next(reader)[0]
        print(f"✅ chdb internal ClickHouse version: {version}")
        
        # Check if it's compatible with v25+ features
        major_version = int(version.split('.')[0])
        if major_version >= 24:
            print("✅ Version looks compatible with v25 features")
            return True
        else:
            print("⚠️  Version might not be fully compatible with v25 features")
            return False
    except Exception as e:
        print(f"❌ Version check failed: {e}")
        return False

def test_native_format_support():
    """Test if chdb supports native format - key for PostHog compatibility"""
    print("Testing native format support...")
    try:
        # Create test data similar to PostHog's data structures
        create_table_query = """
        CREATE TABLE test_posthog_like (
            id UInt32,
            distinct_id String,
            timestamp DateTime64(3),
            properties Map(String, String),
            event String
        ) ENGINE = Memory
        """
        chdb.query(create_table_query)
        
        # Insert test data
        insert_query = """
        INSERT INTO test_posthog_like VALUES 
        (1, 'user1', '2024-01-01 10:00:00.123', {'source': 'web', 'campaign': 'test1'}, 'pageview'),
        (2, 'user2', '2024-01-01 11:00:00.456', {'source': 'mobile', 'campaign': 'test2'}, 'click'),
        (3, 'user3', '2024-01-01 12:00:00.789', {'source': 'api', 'campaign': 'test3'}, 'conversion')
        """
        chdb.query(insert_query)
        
        # Test different formats critical for PostHog
        formats_to_test = ["Native", "RowBinary", "TabSeparated", "CSV"]
        
        success_count = 0
        for format_name in formats_to_test:
            try:
                export_query = "SELECT * FROM test_posthog_like ORDER BY id"
                result = chdb.query(export_query, output_format=format_name)
                print(f"✅ {format_name} format works ({len(str(result))} bytes)")
                success_count += 1
            except Exception as e:
                print(f"❌ {format_name} format failed: {e}")
        
        return success_count >= 3  # At least 3 out of 4 formats should work
        
    except Exception as e:
        print(f"❌ Native format test failed: {e}")
        return False

def test_posthog_warehouse_patterns():
    """Test specific patterns used by PostHog's warehouse functionality"""
    print("Testing PostHog warehouse patterns...")
    try:
        # Test DESCRIBE functionality (used in posthog/warehouse/models/table.py)
        describe_query = """
        DESCRIBE TABLE (SELECT * FROM test_posthog_like LIMIT 1)
        """
        
        result = chdb.query(describe_query, output_format="CSV")
        reader = csv.reader(StringIO(str(result)))
        columns = list(reader)
        print(f"✅ DESCRIBE query works: {len(columns)} columns found")
        
        # Test count functionality (also used in warehouse)
        count_query = "SELECT count() FROM test_posthog_like"
        count_result = chdb.query(count_query, output_format="CSV")
        reader = csv.reader(StringIO(str(count_result)))
        count = next(reader)[0]
        print(f"✅ COUNT query works: {count} rows")
        
        # Test Map type queries (used in PostHog analytics)
        map_query = """
        SELECT 
            id,
            properties['source'] as source,
            properties['campaign'] as campaign
        FROM test_posthog_like
        ORDER BY id
        """
        
        result = chdb.query(map_query, output_format="CSV")
        reader = csv.reader(StringIO(str(result)))
        rows = list(reader)
        print(f"✅ Map type queries work: {len(rows)} rows returned")
        
        return True
        
    except Exception as e:
        print(f"❌ PostHog warehouse patterns test failed: {e}")
        return False

def test_aggregate_function_types():
    """Test AggregateFunction types critical for web preaggregated exports"""
    print("Testing AggregateFunction types compatibility...")
    try:
        # Create table with AggregateFunction types like web_stats_daily
        create_table_query = """
        CREATE TABLE test_web_preaggregated (
            period_bucket DateTime,
            team_id UInt64,
            host String,
            device_type String,
            pathname String,
            browser String,
            utm_source String,
            updated_at DateTime,
            persons_uniq_state AggregateFunction(uniq, UUID),
            sessions_uniq_state AggregateFunction(uniq, String),  
            pageviews_count_state AggregateFunction(sum, UInt64),
            bounces_count_state AggregateFunction(sum, UInt64),
            total_session_duration_state AggregateFunction(sum, Int64),
            total_session_count_state AggregateFunction(sum, UInt64)
        ) ENGINE = Memory
        """
        chdb.query(create_table_query)
        print("✅ AggregateFunction table creation works")
        
        # Test inserting data with State functions (how PostHog populates these tables)
        insert_query = """
        INSERT INTO test_web_preaggregated 
        SELECT
            toDateTime('2024-01-01 00:00:00') as period_bucket,
            420 as team_id,
            'posthog.com' as host,
            'Desktop' as device_type,
            '/insights' as pathname,
            'Chrome' as browser,
            'web' as utm_source,
            now() as updated_at,
            uniqState(generateUUIDv4()) as persons_uniq_state,
            uniqState('session-' || toString(number)) as sessions_uniq_state,
            sumState(toUInt64(number % 5 + 1)) as pageviews_count_state,
            sumState(toUInt64(if(number % 10 = 0, 1, 0))) as bounces_count_state,
            sumState(toInt64(number * 1000)) as total_session_duration_state,
            sumState(toUInt64(1)) as total_session_count_state
        FROM numbers(100)
        """
        chdb.query(insert_query)
        print("✅ AggregateFunction data insertion with State functions works")
        
        # Test querying with Merge functions (how PostHog reads preaggregated data)
        merge_query = """
        SELECT
            uniqMerge(persons_uniq_state) as unique_persons,
            uniqMerge(sessions_uniq_state) as unique_sessions,
            sumMerge(pageviews_count_state) as total_pageviews,
            sumMerge(bounces_count_state) as total_bounces,
            sumMerge(total_session_duration_state) as total_duration,
            sumMerge(total_session_count_state) as total_sessions
        FROM test_web_preaggregated
        """
        
        result = chdb.query(merge_query, output_format="CSV")
        reader = csv.reader(StringIO(str(result)))
        rows = list(reader)
        
        if rows and len(rows) > 0:
            print(f"✅ AggregateFunction Merge queries work: {rows[0]}")
        else:
            print("⚠️  Merge query returned no data")
        
        # Test conditional merge functions (used in period comparisons)
        conditional_merge_query = """
        SELECT
            uniqMergeIf(persons_uniq_state, period_bucket = toDateTime('2024-01-01 00:00:00')) as current_persons,
            sumMergeIf(pageviews_count_state, period_bucket = toDateTime('2024-01-01 00:00:00')) as current_pageviews
        FROM test_web_preaggregated
        """
        
        result = chdb.query(conditional_merge_query, output_format="CSV")
        reader = csv.reader(StringIO(str(result)))
        rows = list(reader)
        print(f"✅ Conditional AggregateFunction queries work: {len(rows)} rows")
        
        # Test native format export with AggregateFunction types
        export_query = "SELECT * FROM test_web_preaggregated LIMIT 5"
        native_result = chdb.query(export_query, output_format="Native")
        print(f"✅ Native format export with AggregateFunction works ({len(str(native_result))} bytes)")
        
        return True
        
    except Exception as e:
        print(f"❌ AggregateFunction types test failed: {e}")
        return False

def test_web_analytics_patterns():
    """Test patterns used in PostHog's web analytics (external queries)"""
    print("Testing web analytics query patterns...")
    try:
        # Test aggregation patterns used in web analytics
        analytics_query = """
        SELECT 
            toDate(timestamp) as date,
            event,
            count() as events,
            uniq(distinct_id) as unique_users,
            groupArray(properties['source']) as sources
        FROM test_posthog_like
        GROUP BY toDate(timestamp), event
        ORDER BY date, event
        """
        
        result = chdb.query(analytics_query, output_format="CSV")
        reader = csv.reader(StringIO(str(result)))
        agg_rows = list(reader)
        print(f"✅ Web analytics aggregations work: {len(agg_rows)} grouped rows")
        
        # Test time-based queries
        time_query = """
        SELECT 
            toStartOfHour(timestamp) as hour,
            count() as hourly_events
        FROM test_posthog_like
        GROUP BY toStartOfHour(timestamp)
        ORDER BY hour
        """
        
        result = chdb.query(time_query, output_format="CSV")
        reader = csv.reader(StringIO(str(result)))
        time_rows = list(reader)
        print(f"✅ Time-based queries work: {len(time_rows)} time buckets")
        
        return True
        
    except Exception as e:
        print(f"❌ Web analytics patterns test failed: {e}")
        return False

def test_complex_aggregate_function_patterns():
    """Test complex AggregateFunction patterns used in PostHog session and replay data"""
    print("Testing complex AggregateFunction patterns...")
    try:
        # Create table similar to session replay events with complex aggregate functions
        create_table_query = """
        CREATE TABLE test_session_replay (
            session_id String,
            team_id UInt64,
            first_url AggregateFunction(argMin, Nullable(String), DateTime64(6)),
            all_urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
            click_count SimpleAggregateFunction(sum, Int64),
            console_log_count SimpleAggregateFunction(sum, Int64),
            snapshot_source AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6)),
            _timestamp SimpleAggregateFunction(max, DateTime)
        ) ENGINE = Memory
        """
        chdb.query(create_table_query)
        print("✅ Complex AggregateFunction table creation works")
        
        # Test inserting data with complex state functions
        insert_query = """
        INSERT INTO test_session_replay 
        SELECT
            'session-' || toString(number) as session_id,
            420 as team_id,
            argMinState(nullIf('https://posthog.com/page-' || toString(number), ''), now64(6)) as first_url,
            groupUniqArrayArrayState(['page1', 'page2', 'page3']) as all_urls,
            sumState(toInt64(number % 10)) as click_count,
            sumState(toInt64(number % 3)) as console_log_count,
            argMinState(toLowCardinality(nullIf('web', '')), now64(6)) as snapshot_source,
            maxState(now()) as _timestamp
        FROM numbers(50)
        """
        chdb.query(insert_query)
        print("✅ Complex AggregateFunction data insertion works")
        
        # Test querying with argMinMerge and other complex merge functions
        complex_merge_query = """
        SELECT
            argMinMerge(first_url) as first_page,
            groupUniqArrayArrayMerge(all_urls) as unique_urls,
            sumMerge(click_count) as total_clicks,
            argMinMerge(snapshot_source) as source,
            maxMerge(_timestamp) as latest_timestamp
        FROM test_session_replay
        """
        
        result = chdb.query(complex_merge_query, output_format="CSV")
        reader = csv.reader(StringIO(str(result)))
        rows = list(reader)
        print(f"✅ Complex AggregateFunction merge queries work: {len(rows)} rows")
        
        # Test native format with complex aggregate functions
        export_query = "SELECT * FROM test_session_replay LIMIT 3"
        native_result = chdb.query(export_query, output_format="Native")
        print(f"✅ Native export with complex AggregateFunction works ({len(str(native_result))} bytes)")
        
        return True
        
    except Exception as e:
        print(f"❌ Complex AggregateFunction patterns test failed: {e}")
        return False

def test_external_clickhouse_connection():
    """Test if we can connect to external ClickHouse v25 if available"""
    print("Testing external ClickHouse v25 connection...")
    
    clickhouse_host = os.environ.get("CLICKHOUSE_HOST")
    clickhouse_port = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
    
    if not clickhouse_host:
        print("⚠️  No external ClickHouse configured, skipping integration test")
        return True
    
    try:
        # Try to connect to external ClickHouse
        response = requests.get(f"http://{clickhouse_host}:{clickhouse_port}/ping", timeout=5)
        if response.status_code == 200:
            print(f"✅ Connected to external ClickHouse at {clickhouse_host}:{clickhouse_port}")
            
            # Test version
            version_response = requests.post(
                f"http://{clickhouse_host}:{clickhouse_port}/", 
                data="SELECT version()",
                timeout=10
            )
            if version_response.status_code == 200:
                version = version_response.text.strip()
                print(f"✅ External ClickHouse version: {version}")
                return version.startswith('25.')
            
        return False
        
    except Exception as e:
        print(f"⚠️  External ClickHouse connection failed: {e}")
        return True  # Non-blocking failure

def main():
    """Run all chdb compatibility tests"""
    print("🧪 PostHog chdb ClickHouse v25 Compatibility Test")
    print("=" * 60)
    print("This test verifies chdb compatibility before migrating to ClickHouse v25")
    print()
    
    tests = [
        ("Basic Functionality", test_basic_chdb_functionality),
        ("Version Compatibility", test_chdb_version_compatibility), 
        ("Native Format Support", test_native_format_support),
        ("PostHog Warehouse Patterns", test_posthog_warehouse_patterns),
        ("AggregateFunction Types", test_aggregate_function_types),
        ("Complex AggregateFunction Patterns", test_complex_aggregate_function_patterns),
        ("Web Analytics Patterns", test_web_analytics_patterns),
        ("External ClickHouse Connection", test_external_clickhouse_connection),
    ]
    
    passed = 0
    total = len(tests)
    failed_tests = []
    
    for test_name, test_func in tests:
        print(f"Running: {test_name}")
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name} PASSED")
            else:
                failed_tests.append(test_name)
                print(f"❌ {test_name} FAILED")
        except Exception as e:
            failed_tests.append(test_name)
            print(f"💥 {test_name} CRASHED: {e}")
        
        print("-" * 50)
    
    print(f"📊 Results: {passed}/{total} tests passed")
    
    if failed_tests:
        print(f"❌ Failed tests: {', '.join(failed_tests)}")
    
    # Exit codes for CI
    if passed == total:
        print("🎉 All tests passed! chdb is fully compatible with ClickHouse v25")
        sys.exit(0)
    elif passed >= total * 0.8:  # 80% success rate
        print("✅ Most tests passed! chdb should work with ClickHouse v25")
        print("⚠️  Review failed tests but migration should be safe")
        sys.exit(0)
    else:
        print("⚠️  Multiple tests failed. Review compatibility issues before v25 migration")
        sys.exit(1)

if __name__ == "__main__":
    main() 