---
title: How to run migrations on PostHog Cloud
sidebar: Handbook
showTitle: true
---

This document outlines how to do large-scale data migrations on PostHog Cloud without using [Async Migrations](/handbook/engineering/databases/async-migrations).

## Background

Start of 2022 we [wanted to change events table schema to better support our querying patterns](https://github.com/PostHog/posthog/issues/5684).

Doing this migration on cloud took several months and several false starts.

## Migration strategy

[Read guide to event ingestion before this](/handbook/engineering/databases/event-ingestion).

Desired goals on the migration:
1. It should be correct - no duplicated or missing data
2. It should be timely - can be completed within a reasonable amount of time
3. It should cause minimal ingestion delay
4. It should keep materialized columns

The rough migration strategy looks like this:

<details><summary>1. Create a new staging table _without_ materialized columns on 1 node on each of the shards.</summary>

```sql runInPostHog=false
CREATE TABLE posthog.sharded_events_ordered_by_event(
    `uuid` UUID,
    `event` String,
    `properties` String,
    `timestamp` DateTime64(6, 'UTC'),
    `team_id` Int64,
    `distinct_id` String,
    `elements_hash` String,
    `created_at` DateTime64(6, 'UTC'),
    `_timestamp` DateTime,
    `_offset` UInt64,
    `elements_chain` String,
    `$group_0` String MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), concat('^[', regexpQuoteMeta('"'), ']*|[', regexpQuoteMeta('"'), ']*$'), ''),
    `$group_1` String MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), concat('^[', regexpQuoteMeta('"'), ']*|[', regexpQuoteMeta('"'), ']*$'), ''),
    `$group_2` String MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), concat('^[', regexpQuoteMeta('"'), ']*|[', regexpQuoteMeta('"'), ']*$'), ''),
    `$group_3` String MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), concat('^[', regexpQuoteMeta('"'), ']*|[', regexpQuoteMeta('"'), ']*$'), ''),
    `$group_4` String MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), concat('^[', regexpQuoteMeta('"'), ']*|[', regexpQuoteMeta('"'), ']*$'), ''),
    `$window_id` String MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$window_id'), concat('^[', regexpQuoteMeta('"'), ']*|[', regexpQuoteMeta('"'), ']*$'), ''),
    `$session_id` String MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), concat('^[', regexpQuoteMeta('"'), ']*|[', regexpQuoteMeta('"'), ']*$'), '')
)
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/prod/tables/{shard}/posthog.sharded_events_ordered_by_event3',
    '{replica}',
    _timestamp
) PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
SAMPLE BY cityHash64(distinct_id)
SETTINGS storage_policy = 'hot_to_cold'
```

Note that zookeeper path needs to be unique for this to work.
</details>

<details><summary>2. `INSERT` data from the old table to the new staging table (using settings to enable fast copying) on each of the shards</summary>

```sql runInPostHog=false
set max_block_size=200000, max_insert_block_size=200000, max_threads=20, max_insert_threads=20, optimize_on_insert=0, max_execution_time=0, max_partitions_per_insert_block=100000, max_memory_usage=100000000000

INSERT INTO sharded_events_ordered_by_event(uuid, event, properties, timestamp, team_id, distinct_id, elements_hash, created_at, _timestamp, _offset, elements_chain)
SELECT uuid, event, properties, timestamp, team_id, distinct_id, elements_hash, created_at, _timestamp, _offset, elements_chain
FROM sharded_events
```

</details>

<details><summary>3. Attach a _new_ kafka topic + materialized view + distributed table to catch up with the main table</summary>

```sql runInPostHog=false

CREATE TABLE posthog.writable_events2
(
    `uuid` UUID,
    `event` String,
    `properties` String,
    `timestamp` DateTime64(6, 'UTC'),
    `team_id` Int64,
    `distinct_id` String,
    `elements_hash` String,
    `created_at` DateTime64(6, 'UTC'),
    `_timestamp` DateTime,
    `_offset` UInt64,
    `elements_chain` String
)
ENGINE = Distributed('posthog', 'posthog', 'sharded_events_ordered_by_event', sipHash64(distinct_id))


CREATE TABLE posthog.kafka_events_proto2 (`uuid` String, `event` String, `properties` String, `timestamp` DateTime64(6, 'UTC'), `team_id` UInt64, `distinct_id` String, `created_at` DateTime64(6, 'UTC'), `elements_chain` String) ENGINE = Kafka SETTINGS kafka_broker_list = 'XXX', kafka_topic_list = 'clickhouse_events_proto', kafka_group_name = 'prod_kafka_proto_events_group2', kafka_format = 'Protobuf', kafka_schema = 'eventsmsg:EventMsg', kafka_skip_broken_messages = 10

CREATE MATERIALIZED VIEW posthog.events_mv2 TO posthog.writable_events2 (`uuid` UUID, `event` String, `properties` String, `timestamp` DateTime64(6, 'UTC'), `team_id` Int64, `distinct_id` String, `elements_chain` String, `created_at` DateTime64(6, 'UTC'), `_timestamp` DateTime, `_offset` UInt64) AS SELECT uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, created_at, _timestamp, _offset FROM posthog.kafka_events_proto2

```

Note that the kafka consumer group name needs be different from the previous one to make sure everything gets consumed

</details>
<details><summary>4. Create the correct materialized columns on the staging table</summary>

```sql runInPostHog=false

select concat('ALTER TABLE sharded_events_ordered_by_event ADD COLUMN ', name, ' VARCHAR MATERIALIZED ', default_expression, ';') from system.columns where table = 'sharded_events' and default_kind = 'DEFAULT' format TSV

clickhouse-client --queries-file 2022-01-23-sharded_events_materialized.sql
```

The following commands worked for me during this migration, this will need to be adjusted for the next migration

</details>
<details><summary>5. Remove duplicates from the dataset and materialize columns</summary>

```sql runInPostHog=false
OPTIMIZE TABLE sharded_events_ordered_by_event FINAL DEDUPLICATE
```

Run this on each of the shards.
</details>

<details><summary>6. Verify the copy results</summary>

Some sample queries used to drill into issues:

```sql runInPostHog=false
select _table, count(), max(_timestamp) from merge('posthog', 'sharded_events.*') group by _table;

select _table, count(), max(_timestamp) from merge('posthog', 'sharded_events.*') where timestamp < '2022-02-24' group by _table;

select _table, team_id, count() c from merge('posthog', 'sharded_events.*') group by _table, team_id order by c limit 10;


select _table, toYYYYMM(timestamp), count() c from merge('posthog', 'sharded_events.*') group by _table, toYYYYMM(timestamp) order by c desc limit 20;

SELECT partition, max(c) - min(c) diff
FROM (
    select _table, toYYYYMM(timestamp) partition, count() c from merge('posthog', 'sharded_events.*') group by _table, toYYYYMM(timestamp)
)
GROUP BY partition
ORDER BY diff DESC
LIMIT 10;


SELECT partition, date, max(c) - min(c) diff
FROM (
    select _table, toYYYYMM(timestamp) partition, toDate(timestamp) date,  count() c
    from merge('posthog', 'sharded_events.*')
    where toYYYYMM(timestamp) = '202201'
    group by _table, toYYYYMM(timestamp), date
)
GROUP BY partition, date
ORDER BY diff DESC
LIMIT 10;

select _table, count(), uniqExact(uuid)
from merge('posthog', 'sharded_events.*')
WHERE toDate(timestamp) = '2022-01-29'
GROUP BY _table;
```

</details>
<details><summary>7. Replicate the new staging table onto each of the nodes on all shards.</summary>

Get the `create_table_query` for the new table from system.tables and run it on all the remaining nodes.

</details>
<details><summary>8. Stop ingestion, swap the staging and main table names</summary>

```sql runInPostHog=false

DROP TABLE IF EXISTS events_mv ON CLUSTER posthog;
DROP TABLE IF EXISTS events_mv2 ON CLUSTER posthog;
DROP TABLE IF EXISTS kafka_events_proto ON CLUSTER posthog;
DROP TABLE IF EXISTS kafka_events_proto2 ON CLUSTER posthog;
DROP TABLE IF EXISTS writable_events2 ON CLUSTER posthog;
RENAME TABLE sharded_events TO sharded_events_20220203_backup, sharded_events_ordered_by_event TO sharded_events ON CLUSTER posthog;
CREATE TABLE posthog.kafka_events_proto (`uuid` String, `event` String, `properties` String, `timestamp` DateTime64(6, 'UTC'), `team_id` UInt64, `distinct_id` String, `created_at` DateTime64(6, 'UTC'), `elements_chain` String) ENGINE = Kafka SETTINGS kafka_broker_list = 'X', kafka_group_name = 'prod_kafka_proto_events_group2', kafka_format = 'Protobuf', kafka_schema = 'eventsmsg:EventMsg', kafka_skip_broken_messages = 10;
CREATE MATERIALIZED VIEW posthog.events_mv TO posthog.writable_events (`uuid` UUID, `event` String, `properties` String, `timestamp` DateTime64(6, 'UTC'), `team_id` Int64, `distinct_id` String, `elements_chain` String, `created_at` DateTime64(6, 'UTC'), `_timestamp` DateTime, `_offset` UInt64) AS SELECT uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, created_at, _timestamp, _offset FROM posthog.kafka_events_proto;
```

Take care that consumer group names are correct for the migration

</details>
<details><summary>9. Drop old table once all is OK.</summary>

</details>

Click on any of the sections to see relevant SQL or commands run during the previous migration.


### How were the migrations run?

In a tmux session on each of the nodes. Metabase isn't the ideal tool for this due to a lack of progress bars.

### Why copy this way?

Some [benchmarking](https://github.com/PostHog/posthog/issues/5684#issuecomment-1016413621) was done to find the most efficient copying data.

Copying in medium-sized chunks, not touching the network and avoiding re-sorting won out at roughly 1M rows per second. Including materialized columns or immediately replicating also would have slowed the overall time down.

The settings used during copy were:

```
set max_block_size=200000, max_insert_block_size=200000, max_threads=20, max_insert_threads=20, optimize_on_insert=0, max_execution_time=0, max_partitions_per_insert_block=100000, max_memory_usage=100000000000
```

### Why not clickhouse-copier?

We initially attempted the copy using clickhouse-copier, but ran into issues:
1. Copy speed was low (~50000 rows per second)
2. Errors during operations - copier copies tables in chunks and these chunks exceeded 50GB (max_table_size_to_drop setting), causing errors
3. Hard to ensure correctness due to events being ingested from Kafka
4. clickhouse-copier always requires setting `sharding_key`, which slowed down copying
5. Issues with materialized columns (due to the old version of ClickHouse) we were on

### Why not use async migrations?

We created a similar migration for self-hosted that copied data across.

However at the time of writing, schemas on cloud and self-hosted were diverged, making the migrations require different strategies. Also
we assumed in async migrations that the amount of data being migrated was less than on cloud.

That said, learnings from here will help future async migrations.

### Relevant reading

- https://github.com/PostHog/posthog/issues/5684
- https://clickhouse.com/docs/en/operations/utilities/clickhouse-copier/
- https://kb.altinity.com/altinity-kb-setup-and-maintenance/altinity-kb-data-migration/
