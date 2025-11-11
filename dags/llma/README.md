# LLMA (LLM Analytics) Dagster Location

Daily aggregation pipelines for LLM analytics metrics.

## Structure

```text
dags/llma/
├── README.md
├── daily_metrics/
│   ├── config.py                     # Configuration for daily metrics pipeline
│   ├── metrics_daily.py              # Daily aggregation asset and schedule
│   └── sql/
│       ├── event_counts.sql          # Count metrics for AI events
│       └── error_rates.sql           # Error rate metrics for AI events
└── __init__.py
```

## Daily Metrics Pipeline

Aggregates AI event metrics ($ai_trace, $ai_generation, $ai_span,
$ai_embedding) into the `llma_metrics_daily` ClickHouse table.

### Architecture

The pipeline uses a modular SQL template system:

- Each metric type lives in its own `.sql` file under `daily_metrics/sql/`
- Templates are auto-discovered and combined with UNION ALL
- To add a new metric, simply drop a new `.sql` file in the directory

### Output Schema

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

### Current Metrics

- `ai_generation_count`, `ai_trace_count`, etc: Daily event counts per
  team
- `ai_generation_error_rate`, `ai_trace_error_rate`, etc: Error rate as
  percentage (0-100)

### Schedule

Runs daily at 6 AM UTC for the previous day's partition.

### Local Development

The LLMA location is loaded in `.dagster_home/workspace.yaml` for local development.

To test aggregation:

```bash
python test_llma_metrics.py
```

To query results:

```sql
SELECT * FROM llma_metrics_daily WHERE date = today()
```
