# Web Analytics Pre-aggregated Data Jobs

This document describes the web analytics pre-aggregation jobs with daily partitioning, retry strategies, and ClickHouse settings management.

## Key Features

### 🗓️ Daily Partitions
- Data assets use daily partitions starting from 2020-01-01
- Each partition processes one day of data
- Enables incremental processing

### 🔄 Retry Strategies
- Exponential backoff with jitter for ClickHouse operations
- 3 max retries with 30s base delay, up to 300s max delay
- Handles transient ClickHouse errors gracefully

### ⚙️ Flexible ClickHouse Settings
- **Default settings**: Balanced performance (50GB memory limit)
- **High-performance settings**: For large data processing (100GB memory limit)
- **Custom settings**: Merge additional settings via configuration

### 🚦 Concurrency Control
- `max_concurrent: 1` prevents overwhelming ClickHouse cluster
- Sequential execution ensures resource availability

## Jobs Available

### 1. Daily Data Job
```python
web_analytics_daily_data_job
```
- Runs daily at 1 AM UTC via schedule
- Processes previous day's partition
- **Only inserts data** - does not recreate tables
- Uses default ClickHouse settings

### 2. Table Setup Job
```python
web_analytics_table_setup_job
```
- One-time setup for creating tables
- Run manually when needed (e.g., new environment)
- Creates both local and distributed tables

### 3. Recreate All Job
```python
recreate_all_web_analytics_job
```
- **No partitions** - processes all data in one job
- **Includes table setup + all data processing**
- Processes all data from 2020-01-01 to today
- For local development and full rebuilds

## Workflow

### Initial Setup
1. **Create tables** (one-time): Run `web_analytics_table_setup_job`
2. **Process data**: Use daily jobs or recreate-all

### Daily Operations
- **Scheduled daily job**: Runs automatically at 1 AM UTC for previous day
- **Manual daily run**: Can be triggered for specific partitions in Dagster UI

### Key Points
- **ReplacingMergeTree tables**: Tables persist between runs
- **Daily schedule**: Only processes data, doesn't recreate tables
- **Recreate-all job**: No partitions, processes everything at once
- **Concurrency control**: Max 1 concurrent job to protect ClickHouse

## Configuration Options

### Team IDs
```python
"team_ids": [1, 2, 3]  # Default: [1, 2]
```

### ClickHouse Settings
```python
# Use high-performance preset
"use_high_performance_settings": True

# Add custom settings
"extra_clickhouse_settings": "max_threads=32,max_memory_usage=214748364800"
```

## Default ClickHouse Settings

### Standard Settings
```python
DEFAULT_CLICKHOUSE_SETTINGS = {
    "max_execution_time": "1200",                    # 20 minutes
    "max_bytes_before_external_group_by": "21474836480",  # 20GB
    "distributed_aggregation_memory_efficient": "1",
    "max_memory_usage": "53687091200",              # 50GB
    "max_threads": "8",
    "join_algorithm": "hash",
    "optimize_aggregation_in_order": "1",
}
```

### High-Performance Settings
```python
HIGH_PERFORMANCE_CLICKHOUSE_SETTINGS = {
    "max_execution_time": "1600",                    # 26.7 minutes
    "max_bytes_before_external_group_by": "51474836480",  # 48GB
    "distributed_aggregation_memory_efficient": "1",
    "max_memory_usage": "107374182400",             # 100GB
    "max_threads": "16",
    "join_algorithm": "hash",
    "optimize_aggregation_in_order": "1",
}
```

## Local Usage

Use Dagster UI to trigger jobs manually or use the materialize function:

```python
from dagster import materialize, DagsterInstance
from dags.web_preaggregated_internal import (
    web_analytics_preaggregated_tables,
    web_analytics_bounces_daily,
    web_analytics_stats_table_daily,
)

# Setup tables
materialize([web_analytics_preaggregated_tables], instance=DagsterInstance.ephemeral())

# Run for specific partition
materialize(
    [web_analytics_bounces_daily, web_analytics_stats_table_daily],
    instance=DagsterInstance.ephemeral(),
    partition_key="2024-01-15",
    run_config={
        "ops": {
            "web_analytics_bounces_daily": {"config": {"team_ids": [2]}},
            "web_analytics_stats_table_daily": {"config": {"team_ids": [2]}},
        }
    },
)

# Recreate all (no partitions)
materialize(
    [web_analytics_preaggregated_tables, web_analytics_bounces_daily, web_analytics_stats_table_daily],
    instance=DagsterInstance.ephemeral(),
    run_config={
        "ops": {
            "web_analytics_bounces_daily": {"config": {"use_high_performance_settings": True}},
            "web_analytics_stats_table_daily": {"config": {"use_high_performance_settings": True}},
        }
    },
)
```

## Assets

### `web_analytics_preaggregated_tables`
- Creates the base tables and distributed tables
- No partitions (runs once)
- Dependency for other assets

### `web_analytics_bounces_daily`
- Partitioned by day
- Processes bounce rate data
- Table: `web_bounces_daily`

### `web_analytics_stats_table_daily`
- Partitioned by day  
- Processes pageview and user count data
- Table: `web_stats_daily`

## Monitoring

### Logs
Each job logs:
- Date range being processed
- ClickHouse settings used
- Full SQL query for debugging

### Retry Behavior
- Failed jobs automatically retry with exponential backoff
- Check Dagster UI for retry attempts and failure reasons

## Best Practices

1. **Use daily partitions for incremental processing**
2. **Use recreate-all job for full rebuilds**
3. **Monitor ClickHouse cluster resources during execution**
4. **Test custom settings on small datasets first**

## Troubleshooting

### Memory Issues
- Reduce `max_memory_usage` in extra settings
- Use high-performance settings only when needed
- Check ClickHouse cluster capacity

### Timeout Issues
- Increase `max_execution_time`
- Use high-performance settings
- Check for data skew in specific dates

### Concurrency Issues
- Jobs are limited to 1 concurrent execution
- Wait for current job to complete before starting new one
- Check Dagster UI for running jobs 