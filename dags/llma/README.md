# LLMA (LLM Analytics) Dagster Location

Data pipelines for LLM analytics and observability.

## Overview

The LLMA location contains pipelines for aggregating and analyzing AI/LLM
events tracked through PostHog. These pipelines power analytics, cost tracking,
and observability features for AI products.

## Structure

```text
dags/llma/
├── README.md
├── daily_metrics/               # Daily aggregation pipeline
│   ├── README.md               # Detailed pipeline documentation
│   ├── config.py               # Pipeline configuration
│   ├── metrics_daily.py        # Dagster asset and schedule
│   └── sql/                    # Modular SQL templates
│       ├── event_counts.sql    # Event count metrics
│       └── error_rates.sql     # Error rate metrics
└── __init__.py
```

## Pipelines

### Daily Metrics

Aggregates AI event metrics ($ai_trace, $ai_generation, $ai_span,
$ai_embedding) by team and date into the `llma_metrics_daily` ClickHouse
table.

Features:

- Modular SQL template system for easy metric additions
- Event counts and error rates
- Long-format schema for schema-less evolution
- Daily schedule at 6 AM UTC

See [daily_metrics/README.md](daily_metrics/README.md) for detailed
documentation.

## Local Development

The LLMA location is loaded in `.dagster_home/workspace.yaml` for local
development.

View in Dagster UI:

```bash
# Dagster runs on port 3030
open http://localhost:3030
```

Test pipelines:

```bash
python test_llma_metrics.py
```
