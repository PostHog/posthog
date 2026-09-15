# Metric catalog

The catalog first requests metric names and types from `metrics/names/`.
It does not read metric values until a card is near the visible area.

Visible cards enter a shared queue.
After 50 ms, the queue sends up to 20 exact names to `metrics/values/` in one request.
Only one batch runs at a time.
The request uses POST with a JSON `names` array and keeps the current service filter.
The server ignores `value` and `limit` when `names` is present.
It returns up to 24 recent sparkline points per metric.

The catalog matches responses by metric name, not response order.
A service change clears queued cards and makes old responses invalid, including errors.
Failed cards keep the Retry button.
Query budget failures return an error instead of partial results.
The catalog shows the empty state only after a successful request returns no usable points.

Each sparkline needs an explicit width and height.
The card gives the shared `Sparkline` component `w-full h-full` inside a fixed-height container.

## Tests

The component tests check the POST batch after the queue delay.
The Storybook tests use an explicit container width and wait for a visible chart.
They do not wait for every loading placeholder to disappear: offscreen cards stay unloaded until they enter view.

## Metadata migration

Migration `0322_metrics_metadata3_dual_write` adds three metadata tables on the logs cluster.
`metric_series3` partitions by `toDate(last_seen)` and keeps `ReplacingMergeTree(last_seen)`.
Merges retain the latest labelled row for each series within each day.
The expiry timestamp still controls row retention.

`metric_attributes3` includes `metric_name` in its columns, sort key, and materialized view grouping.
Both metric attributes and resource attributes include the metric name.
The sort key also includes `service_name` and `original_expiry_time_bucket` to keep their counts and retention separate during merges.
The hourly buckets, expiry partitions, label filter, and attribute length limits match `metric_attributes2`.

`metric_names3` stores metric names in hourly activity buckets, partitioned by day.
Its sort key is `(team_id, time_bucket, metric_name)` to support recent name lists for one project.
Its materialized view reads only samples where `has_labels` is true, including samples with empty attribute maps.
`AggregatingMergeTree` combines rows across series and services, and retains the maximum original expiry timestamp for each project, hour, and name.
The table records activity from labelled samples, not every sample.
Time filters use the hourly buckets, so discovery can include activity outside the requested range within its boundary hours.
Later readers must use `DISTINCT metric_name` because merges are asynchronous and names repeat across hours.
Queries with other label filters still need series data.

Four new materialized views read `metrics2_input` and write to the new tables.
The existing views continue to write to `metric_series2` and `metric_attributes2`.
The distributed tables and HogQL schemas still read the existing tables.
This phase adds storage and insert work; it does not improve query speed until reads move to the new tables.

### Backfill and read cutover

The migration does not copy historical rows.
Backfill the new destination tables directly after all four materialized views exist on each logs replica.
Do not replay a backfill through `metrics2_input`, because its existing views would also write the raw samples and old metadata again.

Use a source boundary that excludes rows already written by the new views.
Attribute counts use addition, so overlapping writes or repeated backfill batches can count rows twice.
A timestamp boundary alone does not exclude late samples.
Preserve the original expiry timestamps in the backfill.

`metric_series2` retains only the latest row for each series after merges.
Copying it cannot restore earlier daily activity.
Use retained samples and the matching series labels to restore those days.
`metric_attributes2` does not retain metric names, so it cannot supply the new attribute rows alone.
Preserve the `has_labels` filter when rebuilding attribute counts from samples.

For `metric_names3`, use only source samples with `has_labels` set.
Group by project, metric name, and the sample timestamp rounded to the start of its hour.
Keep the maximum original expiry timestamp for each group.
Repeated catalog rows merge with `max`, so overlapping catalog batches do not add counts or shorten retention.
The latest series rows alone cannot restore earlier hourly activity.

Before a read cutover, compare metric names, label pairs, daily series activity, and retention for the same source range.
Check insert latency, materialized view errors, part counts, and storage growth during this phase.
A later migration can move the distributed readers after the backfill is complete.
Keep the old tables until that read cutover is stable.
