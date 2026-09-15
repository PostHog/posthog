# Backfill metrics3 with ingestion running

Use [metrics3-backfill.sql](./metrics3-backfill.sql) to copy retained history into the three metrics3 metadata tables.
Ingestion and all existing materialized views continue to run.
The queries do not create, replace, or clear tables.

This backfill accepts some overlap with live writes.
Attribute counts can be too high where both paths include the same sample.
Series rows converge through replacement, and name rows merge with `max`.
Neither of these tables adds counts when rows overlap.

## Run the queries

1. Check that migration `0323_metrics_metadata3_dual_write` has created all three tables and four views on each logs replica.
2. Select a fixed UTC cutoff near the time the new views started writing.
   Use that cutoff as the final `batch_end`. Do not use the current time for each new batch.
3. Select `batch_start` from the retained history you need. Use small, adjacent ranges for a large backfill.
4. Run the three inserts for each range. Each range includes its start and excludes its end.
5. Record each completed range. Run the attribute insert only once per range.

Run the inserts on the logs ClickHouse cluster with a connection that permits writes.
The SQL uses the physical database name `posthog`. Change it if your deployment uses another name.
Use one replica per independent replication group, normally once per region.
Do not repeat the inserts on every replica or nominal shard.
Check `system.replicas.zookeeper_path` if the replication layout differs from the repository.

For example, pass both query parameters through your configured ClickHouse client:

```bash
clickhouse-client \
  --param_batch_start='2026-01-01 00:00:00' \
  --param_batch_end='2026-01-02 00:00:00' \
  --multiquery < docs/internal/metrics3-backfill.sql
```

These dates are examples. Replace them with your history range and deployment cutoff.
In a SQL editor, replace each parameter with a literal such as `toDateTime64('2026-01-02 00:00:00', 6, 'UTC')`.
Use the same values in all three inserts.
If an insert fails or times out, check its query status before you repeat it.
Repeating an attribute batch can duplicate the whole batch, not just the overlap near the cutoff.

## Expected limits

The cutoff applies to the sample timestamp, not its arrival time.
Late samples can therefore overlap with the backfill.
A cutoff well after the views started can produce more overlap.
This procedure does not promise exact attribute counts.

The raw `metrics2` table supplies timestamps, service names, scalar metadata, and original expiry timestamps.
The queries use only samples with `has_labels` set.
They exclude data whose destination retention has already expired.
Attribute counts count labelled samples, not the metric payload's `count` field.
Metric labels retain the length limit from the live view. Resource labels have no such limit.

Raw samples do not store label maps.
The series and attribute queries join the latest retained maps from `metric_series2`.
The lookup returns one row per series, so duplicate metadata rows do not multiply the counts.
Samples without retained series metadata do not contribute series or attribute rows.
The names query still includes those samples and samples with empty maps.

After each batch, check metric discovery and attribute suggestions for that activity range.
Check query duration and insert errors during the backfill.
Use the [catalog checks](./metrics-catalog.md#performance-checks) before the reader deployment.
