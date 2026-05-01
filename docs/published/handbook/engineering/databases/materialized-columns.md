---
title: Working with ClickHouse materialized columns
sidebar: Handbook
showTitle: true
---

This document outlines what materialized columns in ClickHouse are, how we're making use of them and how to manage them on cloud.

## Background

We currently store JSON data in string columns in clickhouse, reading and parsing that data at query-time. This can be slow due to how "fat" these columns are.

Materialized columns allow us to "store" specific properties stored in JSON as separate columns that are there on disk, making reading these columns up to 25x faster than normal properties.

Also check out our [ClickHouse manual](https://posthog.com/handbook/engineering/clickhouse/working-with-json) and [blog post](https://posthog.com/blog/clickhouse-materialized-columns) for more information.

## Materialized columns in practice

Materialized columns play a huge role in optimizing performance for large clients having difficulties with performance.

This is why we automatically materialize columns and have tooling for creating them manually as well.

Note that materialized columns also require backfilling the materialized columns to be effective - an operation best done on a weekend due to extra load it adds to the cluster.

### Automatic materialization

We have a cron-job which analyzes slow queries ran last week and tries to find properties that are used in these slow queries, materializing some of these. Code for this can be found in `ee/clickhouse/materialized_columns/analyze.py`

Note that this cron can often be disabled due to cluster issues or ongoing data migrations.

See [environment variables documentation](https://posthog.com/docs/self-host/configure/environment-variables) + instance settings for toggles which control this.

### Manual materialization via Dagster

We use Dagster to materialize columns in production. The job is `create_materialized_column` in the `team-clickhouse` location.

- **EU**: https://dagster.cloud/posthog/prod-eu/locations/team-clickhouse/jobs/create_materialized_column/playground
- **US**: https://dagster.cloud/posthog/prod-us/locations/team-clickhouse/jobs/create_materialized_column/playground

To materialize columns, go to the playground for the relevant region and configure the `create_materialized_columns_op` with the properties you want to materialize:

```yaml
ops:
  create_materialized_columns_op:
    config:
      backfill_period_days: 90
      dry_run: false
      properties:
        - $browser_language_prefix
        - $app_namespace
      table: events
      table_column: properties
```

Config options:

- **`table`**: The ClickHouse table to materialize on (e.g. `events`, `person`)
- **`table_column`**: The JSON column containing the properties (e.g. `properties`, `person_properties`, `group_properties`)
- **`properties`**: List of property names to materialize as columns
- **`backfill_period_days`**: How many days of historical data to backfill (typically `90`)
- **`dry_run`**: Set to `true` to preview what would be materialized without making changes

Note that backfilling adds extra load to the cluster, so it's best done on a weekend.
