# LLMA Daily Metrics Pipeline

Daily aggregation of AI event metrics into the `llma_metrics_daily` ClickHouse
table.

## Overview

Aggregates AI event metrics ($ai_trace, $ai_generation, $ai_span,
$ai_embedding) by team and date into a long-format metrics table for efficient
querying.

## Architecture

The pipeline uses a modular SQL template system:

- Each metric type lives in its own `.sql` file under `sql/`
- Templates are auto-discovered and combined with UNION ALL
- To add a new metric, simply drop a new `.sql` file in the directory

### SQL Template Format

Each SQL file should return these columns:

```sql
SELECT
    date(timestamp) as date,
    team_id,
    'metric_name' as metric_name,
    toFloat64(value) as metric_value
FROM events
WHERE ...
```

Templates have access to these Jinja2 variables:

- `event_types`: List of AI event types to aggregate
- `date_start`: Start date for aggregation (YYYY-MM-DD)
- `date_end`: End date for aggregation (YYYY-MM-DD)

## Output Schema

```sql
CREATE TABLE llma_metrics_daily (
    date Date,
    team_id UInt64,
    metric_name String,
    metric_value Float64
) ENGINE = ReplicatedMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (team_id, date, metric_name)
```

Long format allows adding new metrics without schema changes.

## Current Metrics

### Event Counts

Defined in `sql/event_counts.sql`:

- `ai_generation_count`: Number of AI generation events
- `ai_trace_count`: Number of AI trace events
- `ai_span_count`: Number of AI span events
- `ai_embedding_count`: Number of AI embedding events

### Error Rates

Defined in `sql/error_rates.sql`:

- `ai_generation_error_rate`: Percentage of AI generation events with errors
- `ai_trace_error_rate`: Percentage of AI trace events with errors
- `ai_span_error_rate`: Percentage of AI span events with errors
- `ai_embedding_error_rate`: Percentage of AI embedding events with errors

Error detection checks for:

- `$ai_error` property is non-empty
- `$ai_is_error` property is true

## Configuration

See `config.py` for configuration options:

- `partition_start_date`: First date to backfill (default: 2025-01-01)
- `cron_schedule`: Schedule for daily runs (default: 6 AM UTC)
- `max_partitions_per_run`: Max partitions to process in backfill (default: 14)

## Schedule

Runs daily at 6 AM UTC for the previous day's partition.

## Local Development

Test the aggregation pipeline:

```bash
python test_llma_metrics.py
```

Query results in ClickHouse:

```bash
docker exec posthog-clickhouse-1 clickhouse-client --query \
  "SELECT * FROM llma_metrics_daily WHERE date = today() FORMAT Pretty"
```

Or use HogQL in PostHog UI:

```sql
SELECT
    date,
    metric_name,
    sum(metric_value) as total
FROM llma_metrics_daily
WHERE date >= today() - INTERVAL 7 DAY
GROUP BY date, metric_name
ORDER BY date DESC, metric_name
```

## Adding New Metrics

1. Create a new SQL file in `sql/` (e.g., `sql/token_counts.sql`)
2. Use Jinja2 template syntax with `event_types`, `date_start`, `date_end`
3. Return columns: `date`, `team_id`, `metric_name`, `metric_value`
4. The pipeline will automatically discover and include it

Example:

```sql
{% for event_type in event_types %}
{% set metric_name = event_type.lstrip('$') + '_tokens' %}
SELECT
    date(timestamp) as date,
    team_id,
    '{{ metric_name }}' as metric_name,
    toFloat64(sum(JSONExtractInt(properties, '$ai_total_tokens'))) as metric_value
FROM events
WHERE event = '{{ event_type }}'
  AND timestamp >= toDateTime('{{ date_start }}', 'UTC')
  AND timestamp < toDateTime('{{ date_end }}', 'UTC')
GROUP BY date, team_id
HAVING metric_value > 0
{% if not loop.last %}
UNION ALL
{% endif %}
{% endfor %}
```
