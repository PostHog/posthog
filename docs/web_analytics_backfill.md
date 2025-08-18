# Web Analytics Pre-Aggregated Data Backfill System

## Overview

This document describes the automated backfill system for web analytics pre-aggregated tables. The system automatically detects teams with missing data and triggers backfill operations using Dagster's partition-based execution model.

## Architecture

### Components

1. **Backfill Detection Logic** (`dags/web_preaggregated_backfill.py`)
   - Direct ClickHouse query detection for missing partitions
   - 80/20 rule implementation: only runs backfill for meaningful amounts of missing data (≥3 partitions)

2. **Dagster Integration**
   - Asset: `web_analytics_backfill_detector` - detects missing data
   - Sensor: `web_analytics_backfill_sensor` - triggers backfill every 6 hours
   - Schedule: `web_analytics_backfill_schedule` - daily backfill check at 2 AM UTC

3. **Dagster Jobs** - CLI-runnable jobs for manual operations and diagnostics

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WEB_ANALYTICS_BACKFILL_LOOKBACK_DAYS` | 30 | How many days back to check for missing data |
| `WEB_ANALYTICS_BACKFILL_MAX_PARTITIONS_PER_RUN` | 7 | Maximum partitions to backfill in a single run |

## Usage

### Automatic Operation

The system runs automatically via:
- **Sensor**: Every 6 hours, checks for missing data and triggers immediate backfill
- **Schedule**: Daily at 2 AM UTC, performs comprehensive check and backfill

### Manual Operation via Dagster CLI

All manual operations are now centralized in Dagster and run via `dagster` CLI:

```bash
# Check for missing data
dagster job execute -j check_missing_data_job

# Show detailed missing data (default: 7 days)
dagster job execute -j show_data_gaps_job

# Show detailed missing data (custom period)
dagster job execute -j show_data_gaps_job -c '{"days_back": 14}'

# View available jobs
dagster job list

# View job details
dagster job print -j check_missing_data_job
```

### Available Dagster Jobs

| Job Name | Purpose | Configuration |
|----------|---------|---------------|
| `check_missing_data_job` | Diagnostic - check for missing partitions | None |
| `show_data_gaps_job` | Diagnostic - detailed gap analysis | `{"days_back": 7}` |

## How It Works

### Detection Process

**Direct Query Method**:
- Directly queries ClickHouse tables to find missing partitions for enabled teams
- Uses efficient CTE-based queries to compare expected vs existing partitions
- Reliable and straightforward approach without additional state tracking

### Backfill Decision Logic

The system implements a "Pareto (80/20)" approach:
- Only triggers backfill if ≥3 partitions are missing across all tables
- Limits backfill to configurable max partitions per run (default: 7)
- Prioritizes recent missing data over old gaps

### Execution Flow

1. **Detection**: Identify teams with missing data periods
2. **Filtering**: Apply 80/20 rule to determine if backfill is needed
3. **Partitioning**: Generate Dagster run requests for missing partition dates
4. **Execution**: Dagster handles the actual backfill using existing assets
5. **Tracking**: Record backfill status to prevent duplicates

## Tables Monitored

- `web_pre_aggregated_stats`
- `web_pre_aggregated_bounces`

## Integration Points

### With Existing Web Analytics Pipeline

The backfill system integrates with:
- **Team Selection**: Uses `get_team_ids_from_sources()` to get enabled teams
- **Pre-aggregation Jobs**: Reuses existing `web_pre_aggregate_job` for backfill execution
- **Partition Definition**: Uses same `DailyPartitionsDefinition(start_date="2024-01-01")`

### With Dagster Assets

- Depends on `web_analytics_team_selection` asset
- Triggers existing `web_pre_aggregated_bounces` and `web_pre_aggregated_stats` assets
- Uses standard Dagster backfill policies and run requests

## Monitoring and Observability

### Metrics Available

- **Detection Asset**: Provides metadata about missing partitions, affected tables, and backfill decisions
- **Dagster Logs**: Track detection results, backfill decisions, and execution status

### Logs and Alerts

The system logs comprehensive information about:
- Missing data detection results
- Backfill decisions and reasoning  
- ClickHouse query execution results
- Error conditions and query failures

### Dashboard Integration

The backfill detector asset materializes with metadata that can be used for:
- Monitoring dashboard creation
- Alert threshold configuration
- Historical backfill trend analysis

## Troubleshooting

### Common Issues

1. **No backfill triggered despite missing data**
   - Check if missing partitions < 3 (below threshold)
   - Verify enabled teams are correctly identified
   - Check sensor/schedule logs for skip reasons

2. **Backfill runs but doesn't fill gaps**
   - Verify team selection includes affected teams
   - Check ClickHouse dictionary reload status
   - Validate partition date formatting

3. **Performance issues with detection**
   - Monitor ClickHouse query performance 
   - Consider reducing lookback days for large team counts
   - Check enabled team count and optimize team selection queries

### Debugging with Dagster CLI

```bash
# Check current missing data status
dagster job execute -j check_missing_data_job

# Detailed gap analysis with custom timeframe
dagster job execute -j show_data_gaps_job -c '{"days_back": 14}'

# View job execution history
dagster run list

# View specific run details
dagster run logs <run_id>

# Monitor asset materializations
dagster asset materialize -s web_analytics_backfill_detector
```

## Future Enhancements

### Planned Improvements

1. **Smart Gap Detection**: Detect gaps based on team activity patterns rather than calendar days
2. **Priority-Based Backfill**: Prioritize high-value teams or recent data gaps
3. **Incremental Coverage Updates**: Only update coverage for teams with recent activity
4. **Cross-Table Consistency**: Ensure both bounces and stats tables have consistent data ranges
5. **Cost Optimization**: Skip backfill for teams with minimal data or low query volume

### Monitoring Enhancements

1. **Backfill Success Rate Metrics**: Track percentage of successful vs failed backfills
2. **Data Freshness SLA Tracking**: Monitor teams falling behind data freshness requirements
3. **Resource Usage Monitoring**: Track ClickHouse resource consumption from backfill operations

## Testing

The system includes comprehensive tests in `dags/tests/test_web_preaggregated_backfill.py`:
- Unit tests for direct query detection logic
- Mocked Dagster asset execution tests
- Backfill decision logic tests
- Edge case and error condition tests

Run tests with:
```bash
python -m pytest dags/tests/test_web_preaggregated_backfill.py -v
```