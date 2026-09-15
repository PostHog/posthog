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

Migration `0323_metrics_metadata3_dual_write` adds three metadata tables on the logs cluster.
`metric_series3` partitions by `toDate(original_expiry_timestamp)` and keeps `ReplacingMergeTree(last_seen)`.
Merges retain the latest labelled row for each series within each expiry day.
The expiry timestamp still controls row retention.
Expiry partitions keep rows with different expiry dates in separate parts, so later expiry dates do not delay removal of earlier parts.
A query for one activity day can read several expiry partitions.
Series rows do not provide complete daily activity history.

`metric_attributes3` includes `metric_name` in its columns, sort key, and materialized view grouping.
Both metric attributes and resource attributes include the metric name.
The sort key also includes `service_name` and `original_expiry_time_bucket` to keep their counts and retention separate during merges.
The hourly buckets, expiry partitions, label filter, and attribute length limits match `metric_attributes2`.

`metric_names3` stores metric names in hourly activity buckets, partitioned by expiry day.
The separate `original_expiry_time_bucket` column has type `DateTime64(0)` and contains the source expiry timestamp rounded down to the hour.
The partition key is `toDate(original_expiry_time_bucket)`.
Its sort key is `(team_id, time_bucket, metric_name, original_expiry_time_bucket)` to support recent name lists for one project.
The view grouping and sort key include the expiry hour, so rows with different expiry hours cannot merge.
Its materialized view reads only samples where `has_labels` is true, including samples with empty attribute maps.
`AggregatingMergeTree` combines rows across series and services for each project, activity hour, name, and expiry hour.
It retains the maximum `original_expiry_timestamp` within each group. This aggregate controls TTL and remains separate from both bucket columns.
The table records activity from labelled samples, not every sample.
Time filters use the hourly buckets, so discovery can include activity outside the requested range within its boundary hours.
Readers must group by metric name because merges are asynchronous and names repeat across activity and expiry buckets.
Queries with other label filters still need series data.

Four new materialized views read `metrics2_input` and write to the new tables.
The existing views continue to write to `metric_series2` and `metric_attributes2`.
HogQL `posthog.metric_series` reads `metric_series3`, and `posthog.metric_attributes` reads `metric_attributes3`.
HogQL `posthog.metric_names` reads `metric_names3`.
These replicated tables use the logs workload and its database connection.
Raw samples still use `posthog.metrics`, which reads `metrics2` through its distributed table.

The unscoped picker selects a bounded name list from hourly activity before it reads series types.
Exact search matches come first, followed by the latest activity hour and metric name.
The final metadata read excludes series outside the exact lookback.
If the name limit falls in the boundary hour, this check can return fewer names than the limit.
Service-scoped lists and catalog requests use series metadata because the names table has no service column.

The overview keeps distinct series counts across expiry days and reports the latest labelled sample.
Attribute key queries sum precomputed counts from `metric_attributes3` within hourly activity buckets.
The API returns `attribute_count`, and the group-by menu labels it "Attribute occurrences".
These counts include metric and resource attributes from labelled samples. They do not count distinct series.
The first and last buckets can include samples outside the exact requested times.
The first-class `service_name` choice comes first when it matches the search, with a null count and no count badge.
Other keys follow by occurrence count, then name. The response limit includes the service choice.
Opening the group-by menu sends its request immediately. Typed searches use a short delay.
Attribute value queries accept an optional `metricName` and use the metric prefix of the attribute sort key.
Each viewer clause supplies its own metric name to both attribute endpoints.

### Backfill and read cutover

The migration does not copy historical rows.
Backfill the new destination tables directly after all four materialized views exist on each logs replica.
Do not replay a backfill through `metrics2_input`, because its existing views would also write the raw samples and old metadata again.

Use a source boundary that excludes rows already written by the new views.
Attribute counts use addition, so overlapping writes or repeated backfill batches can count rows twice.
A timestamp boundary alone does not exclude late samples.
Preserve the original expiry timestamps in the backfill.

`metric_series2` retains only the latest row for each series after merges.
Copying it cannot restore rows for earlier expiry partitions.
Use retained samples and the matching series labels to populate those partitions with the original expiry timestamps.
`metric_attributes2` does not retain metric names, so it cannot supply the new attribute rows alone.
Preserve the `has_labels` filter when rebuilding attribute counts from samples.

For `metric_names3`, use only source samples with `has_labels` set.
Group by project, metric name, and the sample timestamp rounded to the start of its hour.
Also group by `original_expiry_time_bucket`, computed from the source expiry timestamp rounded down to the hour.
Keep the maximum original expiry timestamp for each group.
Repeated catalog rows merge with `max`, so overlapping catalog batches do not add counts or shorten retention.
The latest series rows alone cannot restore earlier hourly activity.

Before a read cutover, compare metric names, label pairs, series presence per expiry day, and retention for the same source range.
Check insert latency, materialized view errors, part counts, and storage growth during this phase.
Deploy the reader change only after the backfill and comparisons pass in each environment.
The old distributed readers remain available for query comparisons and rollback.
Keep the old tables and their materialized views until the reader change is stable.

### Performance checks

Compare the old and new generated SQL on the same project and fixed time range in dev.
Use both empty searches and typed searches, with and without a service or metric filter.
Run each query five times with the uncompressed cache disabled.
Compare median ClickHouse duration, bytes read, and memory in `system.query_log`.
Check returned names, types, counts, and attribute values as well as query time.
Account for hourly picker ordering and the limit at the boundary hour when comparing name lists.

The targets are below one second for the overview, 100 ms for the metric picker, and 500 ms for attribute filters.
Measure the full request and browser load as well as ClickHouse time.
Existing overview spans separate query time from ClickHouse time.
Query timings alone do not prove that the page meets its target.
