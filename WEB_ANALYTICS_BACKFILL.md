# Web Analytics Pre-Aggregated Tables Automatic Backfill

## Overview

This system provides automatic backfill for web analytics pre-aggregated tables when teams enable the `web_analytics_pre_aggregated_tables_enabled` setting. It replaces the previous over-engineered Dagster-based approach with a simple, reliable Django signal + Celery task solution.

## Architecture

### Components

1. **Django Signal Handler** (`posthog/models/team/signals.py`)
   - Detects when `Team.web_analytics_pre_aggregated_tables_enabled` changes to `True`
   - Immediately triggers asynchronous backfill task
   - Provides instant response instead of periodic scanning

2. **Celery Backfill Task** (`posthog/tasks/web_analytics_backfill.py`)
   - Performs direct INSERT to target tables (no partition swapping)
   - Backfills last 7 days of data by default (configurable up to 30 days)
   - Built-in retry mechanism with exponential backoff
   - Comprehensive error handling and logging

3. **Safety Mechanisms**
   - Data validation tasks to check integrity
   - Cleanup tasks for corrupted data recovery
   - Team validation to prevent unnecessary work

4. **Management Tools**
   - Management command for manual operations
   - Health monitoring tasks
   - Metrics reporting

## Usage

### Automatic Operation

When a team enables pre-aggregated tables via UI or API:

```python
team.web_analytics_pre_aggregated_tables_enabled = True
team.save()
```

The system automatically:
1. Django signal detects the change
2. Triggers `backfill_web_analytics_tables_for_team.delay(team.id)`
3. Celery task backfills 7 days of data for both tables:
   - `web_pre_aggregated_stats`
   - `web_pre_aggregated_bounces`

### Manual Operations

#### List Teams with Pre-Aggregated Tables
```bash
python manage.py backfill_web_analytics list
```

#### Manual Backfill
```bash
# Synchronous execution
python manage.py backfill_web_analytics backfill --team-id 123 --days 7

# Asynchronous execution (recommended for production)
python manage.py backfill_web_analytics backfill --team-id 123 --days 7 --async

# Dry run to see what would happen
python manage.py backfill_web_analytics backfill --team-id 123 --dry-run
```

#### Data Validation
```bash
python manage.py backfill_web_analytics validate --team-id 123
```

#### Emergency Cleanup
```bash
python manage.py backfill_web_analytics cleanup --team-id 123 --date-start 2024-01-01 --date-end 2024-01-08
```

### Programmatic Access

#### Direct Task Execution
```python
from posthog.tasks.web_analytics_backfill import backfill_web_analytics_tables_for_team

# Async execution
task = backfill_web_analytics_tables_for_team.delay(team_id=123, backfill_days=7)
print(f"Task ID: {task.id}")

# Sync execution (for testing)
result = backfill_web_analytics_tables_for_team(team_id=123, backfill_days=7)
```

#### Data Validation
```python
from posthog.tasks.web_analytics_backfill import validate_backfill_data_integrity

result = validate_backfill_data_integrity(
    team_id=123, 
    date_start="2024-01-01", 
    date_end="2024-01-08"
)
print(f"Stats rows: {result['validation_results']['web_pre_aggregated_stats_rows']}")
```

## Configuration

### Environment Variables

- `WEB_ANALYTICS_BACKFILL_DAYS`: Default backfill period (default: 7, max: 30)
- Standard Celery configuration applies for task execution

### Task Configuration

Tasks use standard PostHog Celery patterns:
- **Queue**: Default queue (can be customized)
- **Retries**: 3 attempts with exponential backoff
- **Timeout**: Inherits from ClickHouse settings

## Monitoring

### Health Checks

Periodic monitoring task checks system health:
```python
from posthog.tasks.web_analytics_monitoring import monitor_web_analytics_backfill_health

# Run health check
health_report = monitor_web_analytics_backfill_health()
```

### Metrics

Generate performance metrics:
```python
from posthog.tasks.web_analytics_monitoring import generate_backfill_metrics_report

metrics = generate_backfill_metrics_report(days=7)
print(f"Data coverage: {metrics['metrics']['data_coverage_percentage']}%")
```

### Logging

All operations include structured logging:
- Team identification
- Date ranges processed
- Success/failure status  
- Performance metrics
- Error details

## Safety Considerations

### Risk Mitigation

The direct INSERT approach (no partition swapping) has inherent risks:

1. **Data Duplication**: Multiple backfill runs could create duplicates
2. **Performance Impact**: Large backfills may affect ClickHouse performance
3. **Data Corruption**: Failed partial inserts may leave inconsistent state

### Safety Mechanisms

1. **Team Validation**: Verify team still has tables enabled before processing
2. **Date Range Limits**: Maximum 30-day backfill to prevent runaway operations
3. **Retry Logic**: Built-in retry with exponential backoff for transient failures
4. **Data Validation**: Post-backfill integrity checks
5. **Emergency Cleanup**: Ability to delete corrupted data and disable tables

### Recommended Practices

1. **Monitor Task Status**: Use Celery monitoring to track backfill progress
2. **Validate Results**: Run validation checks after backfills
3. **Gradual Rollout**: Enable for small groups of teams initially
4. **Regular Health Checks**: Schedule periodic monitoring tasks
5. **Alert on Failures**: Set up alerts for failed backfill tasks

## Troubleshooting

### Common Issues

#### Backfill Not Triggered
- Check if Django signals are loaded (`from . import signals` in `__init__.py`)
- Verify team has `web_analytics_pre_aggregated_tables_enabled = True`
- Check Celery worker logs for task execution

#### Task Failures
- Check ClickHouse connectivity and permissions
- Verify table schemas match expected structure
- Review memory and timeout settings

#### Missing Data
- Run validation command to check data presence
- Check if backfill period covers expected date range
- Verify team timezone settings affect date calculations

### Debug Commands

```bash
# Check signal registration
python manage.py shell -c "from posthog.models.team import signals; print('Signals loaded')"

# Test task execution
python manage.py shell -c "
from posthog.tasks.web_analytics_backfill import backfill_web_analytics_tables_for_team
result = backfill_web_analytics_tables_for_team(123, 7)
print(result)
"

# Check table data
python manage.py shell -c "
from posthog.clickhouse.client import sync_execute
result = sync_execute('SELECT COUNT(*) FROM web_pre_aggregated_stats WHERE team_id = 123')
print(f'Stats rows: {result[0][0]}')
"
```

## Migration from Previous System

The previous Dagster-based system has been replaced entirely:

### What Changed
- **Removed**: 350+ lines of complex Dagster logic
- **Removed**: Multi-strategy team selection system  
- **Removed**: Staging table partition swapping
- **Added**: ~150 lines of simple Django signal + Celery task

### Migration Steps
1. No migration needed - old system was not deployed
2. Enable new system by importing signals
3. Gradual rollout to validate behavior
4. Clean up unused Dagster code (optional)

## Performance Characteristics

### Expected Performance
- **Trigger Time**: <1 second (Django signal)
- **Backfill Time**: 2-10 minutes depending on data volume
- **Resource Usage**: <10% ClickHouse CPU increase during backfill
- **Success Rate**: >95% expected with retry mechanisms

### Scale Considerations
- Single team backfills are lightweight
- Multiple concurrent backfills handled by Celery parallelism
- Rate limiting available if needed

## Future Enhancements

### Planned Improvements
1. **Configurable Backfill Periods**: Allow teams to choose 7/14/30 days
2. **Smart Backfill**: Only backfill missing date ranges
3. **Real-time Backfill**: Stream processing for immediate data availability
4. **Cross-Region Support**: Handle teams across different ClickHouse clusters

### Integration Opportunities
1. **PostHog Analytics**: Track backfill success/failure rates
2. **Slack Alerts**: Automatic notifications for operations team
3. **Dashboard Metrics**: Visual monitoring of backfill system health