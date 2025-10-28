---
title: Data replication and distributed queries
---

This document provides information on:
- How data replication and Distributed table engine works in ClickHouse
- Sharding MergeTree tables
- How to monitor replication
- How to reason about distributed query execution
- Important settings for distributed query execution
- Doing ad-hoc distributed queries

## Setting up replicated tables

A great guide on setting up replicated tables on a pre-existing cluster can be found in
[ClickHouse documentation](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replication/).

Some important highlights are:
- ClickHouse replication works on a table-by-table level, tables need to be created on all shards (preferably via using `ON CLUSTER`)
- Replication requires a running ZooKeeper setup. In the future, this might be replaced by `clickhouse-keeper`

<blockquote class='warning-note'>
<b>IMPORTANT GOTCHA: </b>

Always use unique ZooKeeper paths for table definitions as re-use can and will lead to data loss. This applies even
if the previous table has been dropped.
</blockquote>

### Sharding replicated tables

Sharding helps scale a dataset by having each node only store part of the data.

To decide whether to shard a table, consider how it's queried and what data it stores:
- Shard: tables that could become too large for a single server (e.g. events, logs, raw analytics data)
- Don't shard: table often JOINed in queries (e.g. persons, groups, cohorts) where the whole dataset is needed.

Sharding also requires care given in the schema - queries touching data should ideally only need to load data from a given shard.

When creating a replicated table, configuring whether a table is sharded or not is done via varying the parameters to a ReplicatedMergeTree engine:

- Example sharded engine: `ReplicatedMergeTree('/zk/some/path/{shard}/tablename', '{replica}')`
- Example unsharded table engine: `ReplicatedMergeTree('/zk/some/path/tablename', '{replica}-{shard}')`

Note that resharding large tables is currently a relatively painful and bespoke operation - be careful choosing a good sharding key.

### Monitoring replication

When doing larger cluster operations, it's often important to keep an eye on replication. The [`system.replication_queue`](https://clickhouse.com/docs/en/operations/system-tables/replication_queue) and [`system.replicated_fetches`](https://clickhouse.com/docs/en/operations/system-tables/replicated_fetches) tables can provide at-a-glance overview of what the system is doing.

## `Distributed` table engine

[`Distributed` table engine](https://clickhouse.com/docs/en/engines/table-engines/special/distributed/) tables
are used to query and write to sharded tables. Note that Distributed engine tables do not store any data on their own
but rather always fan out to `ReplicatedMergeTree` tables on the cluster.

## How writes against `Distributed` tables work

When INSERTing data against Distributed tables, ClickHouse decides which shard each row belongs to and forwards data to relevant shard(s)
based on the sharding_key.

Note that if your underlying table has columns that ClickHouse populates (e.g. ALIAS, MATERIALIZED), it's often necessary to set up
two Distributed tables:
- One for writes containing a minimum set of columns
- Another for reads which contain all columns

## How queries against `Distributed` tables work

When querying Distributed table, you can send the query to any node in the ClickHouse cluster. That node becomes the `coordinator`, which:
1. Figures out what queries individual shards need to execute and queues these queries
2. Once results are in, aggregates the results together and returns an answer

Given local execution is faster than reading data over the network, ClickHouse will usually perform one of the queries locally instead of sending it to another replica of its shard.

Depending on the query, sub-queries executed on other shards might either return already aggregated data or stream entire
datasets across the network. Being aware of which is done is crucial for performance.

### Example query - distributed sums

Consider the following tables:

```sql runInPostHog=false
CREATE TABLE sharded_sensor_values ON CLUSTER 'my_cluster' (
    timestamp DateTime,
    site_id UInt32,
    event VARCHAR,
    uuid UUID,
    metric_value Int32
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/sharded_sensor_values', '{replica}')
ORDER BY (site_id, toStartOfDay(timestamp), event, uuid)
SETTINGS index_granularity = 8192

CREATE TABLE distributed_sensor_values ON CLUSTER 'my_cluster' (
    timestamp DateTime,
    site_id UInt32,
    event VARCHAR,
    uuid UUID,
    metric_value Int32
)
ENGINE = Distributed('my_cluster', 'default', 'sharded_sensor_values', intHash64(site_id))
```

Writes and queries should be made against table `distributed_sensor_values` in this schema. It then distributes the data according to `site_id`.

<details><summary>See query to populate data</summary>

```sql runInPostHog=false
INSERT INTO distributed_sensor_values
SELECT *
FROM generateRandom('timestamp DateTime, site_id UInt8, event VARCHAR, uuid UUID, metric_value Int32', NULL, 10)
LIMIT 100000000
```
</details>

Consider this simple aggregation query executed against `clickhouse01`:

```sql runInPostHog=false
SELECT hostName(), sum(metric_value) FROM distributed_sensor_values GROUP BY hostName()

-- Results:
-- ┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
-- ┃ hostname()   ┃ sum(metric_value) ┃
-- ┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
-- │ clickhouse01 │    -9035836479117 │
-- ├──────────────┼───────────────────┤
-- │ clickhouse03 │    10003905228283 │
-- └──────────────┴───────────────────┘
```

[`hostName` is a clickhouse helper function](https://clickhouse.com/docs/en/sql-reference/functions/other-functions/#hostname) which
returns the hostname query is executed on.

In this case `clickhouse01` was the coordinator node. It:
- sent out a subset of the query to `clickhouse03` on other shard to execute. The query was ```SELECT hostname(), sum(`metric_value`) FROM `default`.`sharded_sensor_values` GROUP BY hostname()```
- ran the query locally, getting aggregated results
- combined both the local and remote results

In this case, minimal network traffic happened since the results of a query could be combined independently.

<details><summary>Click to see full `EXPLAIN` plan</summary>

```
Expression ((Projection + Before ORDER BY))
Header: hostname() String
        sum(metric_value) Int64
  MergingAggregated
  Header: hostname() String
          sum(metric_value) Int64
    SettingQuotaAndLimits (Set limits and quota after reading from storage)
    Header: hostname() String
            sum(metric_value) AggregateFunction(sum, Int32)
      Union
      Header: hostname() String
              sum(metric_value) AggregateFunction(sum, Int32)
        Aggregating
        Header: hostname() String
                sum(metric_value) AggregateFunction(sum, Int32)
          Expression (Before GROUP BY)
          Header: metric_value Int32
                  hostname() String
            SettingQuotaAndLimits (Set limits and quota after reading from storage)
            Header: metric_value Int32
              ReadFromMergeTree
              Header: metric_value Int32
              Indexes:
                PrimaryKey
                  Condition: true
                  Parts: 6/6
                  Granules: 5723/5723
        ReadFromRemote (Read from remote replica)
        Header: hostname() String
                sum(metric_value) AggregateFunction(sum, Int32)
```
 
</details>

### Example query: LIMIT, filter, and aggregate

Consider this query:

```sql runInPostHog=false
SELECT
    site_id,
    uniq(event)
FROM distributed_sensor_values
WHERE timestamp > '2010-01-01' and timestamp < '2023-01-01'
GROUP BY site_id
ORDER BY uniq(event) DESC
LIMIT 20
```

In this case, the query sent to other shards cannot do all the work on its own. Instead, the query being sent to the other shard
would look something like the following:

```sql runInPostHog=false
SELECT
    site_id,
    uniqState(event)
FROM sharded_sensor_values
WHERE timestamp > '2010-01-01' and timestamp < '2023-01-01'
GROUP BY site_id
```

In `EXPLAIN` output, this would be expressed as:

```
ReadFromRemote (Read from remote replica)
Header: site_id UInt32
        uniq(event) AggregateFunction(uniq, String)
```

In this case coordinator needs to receive a lot of data from the other shards to calculate the correct results:
1. It loads data for every site_id on the other shards
2. It cannot just load the unique event count from the other shards, but rather needs to know what events were seen or not

This query is expensive in terms of the amount of data that needs to be transferred over the network.

One thing that makes this query more efficient is `uniqState`, which is a [aggregate function combinator](https://clickhouse.com/docs/en/sql-reference/aggregate-functions/combinators/#-state). It's useful since rather needing to send over all the events, the coordinator can send back an optimized bitmap-like structure that the coordinator can combine with its own results.

<details><summary>Click to see full `EXPLAIN` plan</summary>

```
Expression (Projection)
Header: site_id UInt32
        uniq(event) UInt64
  Limit (preliminary LIMIT (without OFFSET))
  Header: site_id UInt32
          uniq(event) UInt64
    Sorting (Sorting for ORDER BY)
    Header: site_id UInt32
            uniq(event) UInt64
      Expression (Before ORDER BY)
      Header: site_id UInt32
              uniq(event) UInt64
        MergingAggregated
        Header: site_id UInt32
                uniq(event) UInt64
          SettingQuotaAndLimits (Set limits and quota after reading from storage)
          Header: site_id UInt32
                  uniq(event) AggregateFunction(uniq, String)
            Union
            Header: site_id UInt32
                    uniq(event) AggregateFunction(uniq, String)
              Aggregating
              Header: site_id UInt32
                      uniq(event) AggregateFunction(uniq, String)
                Expression (Before GROUP BY)
                Header: site_id UInt32
                        event String
                  SettingQuotaAndLimits (Set limits and quota after reading from storage)
                  Header: site_id UInt32
                          event String
                    ReadFromMergeTree
                    Header: site_id UInt32
                            event String
                    Indexes:
                      PrimaryKey
                        Keys:
                          toStartOfDay(timestamp)
                        Condition: and((toStartOfDay(timestamp) in (-Inf, 1672531200]), (toStartOfDay(timestamp) in [1262304000, +Inf)))
                        Parts: 6/6
                        Granules: 1628/5723
              ReadFromRemote (Read from remote replica)
              Header: site_id UInt32
                      uniq(event) AggregateFunction(uniq, String)

```

</details>

#### Improving this query

This query can be made faster by setting the
[`distributed_group_by_no_merge`](https://clickhouse.com/docs/en/operations/settings/settings/#distributed-group-by-no-merge)
setting, like so:

```sql runInPostHog=false
SELECT
    site_id,
    uniq(event)
FROM distributed_sensor_values
WHERE timestamp > '2010-01-01' and timestamp < '2023-01-01'
GROUP BY site_id
ORDER BY uniq(event) DESC
SETTINGS distributed_group_by_no_merge=1
LIMIT 20
```

After this, the coordinator knows to trust that the data is sharded according to `site_id` and it can send the same query down to other shards.

In `EXPLAIN`, this is represented by the `ReadFromRemote` being done later in the cycle and now reading `UInt64` instead of `AggregateFunction(uniq, String)`:

```
ReadFromRemote (Read from remote replica)
Header: site_id UInt32
        uniq(event) UInt64
```

Takeaway: Proper data layout and usage of query settings can improve queries significantly by doing less work over the network.


<details><summary>Click to see full `EXPLAIN` plan</summary>

```
Header: site_id UInt32
        uniq(event) UInt64
  Union
  Header: site_id UInt32
          uniq(event) UInt64
    Expression (Projection)
    Header: site_id UInt32
            uniq(event) UInt64
      Limit (preliminary LIMIT (without OFFSET))
      Header: site_id UInt32
              uniq(event) UInt64
        Sorting (Sorting for ORDER BY)
        Header: site_id UInt32
                uniq(event) UInt64
          Expression (Before ORDER BY)
          Header: site_id UInt32
                  uniq(event) UInt64
            Aggregating
            Header: site_id UInt32
                    uniq(event) UInt64
              Expression (Before GROUP BY)
              Header: site_id UInt32
                      event String
                SettingQuotaAndLimits (Set limits and quota after reading from storage)
                Header: site_id UInt32
                        event String
                  ReadFromMergeTree
                  Header: site_id UInt32
                          event String
                  Indexes:
                    PrimaryKey
                      Keys:
                        toStartOfDay(timestamp)
                      Condition: and((toStartOfDay(timestamp) in (-Inf, 1672531200]), (toStartOfDay(timestamp) in [1262304000, +Inf)))
                      Parts: 6/6
                      Granules: 1628/5723
    ReadFromRemote (Read from remote replica)
    Header: site_id UInt32
            uniq(event) UInt64
```

</details>

### Query settings

Some noteworthy [query settings](https://clickhouse.com/docs/en/operations/settings/settings/) which affect the behavior of distributed queries are:

- [distributed_group_by_no_merge](https://clickhouse.com/docs/en/operations/settings/settings/#distributed-group-by-no-merge)
- [distributed_push_down_limit](https://clickhouse.com/docs/en/operations/settings/settings/#distributed-push-down-limit)
- [optimize_distributed_group_by_sharding_key](https://clickhouse.com/docs/en/operations/settings/settings/#optimize-distributed-group-by-sharding-key)
- [prefer_localhost_replica](https://clickhouse.com/docs/en/operations/settings/settings/#settings-prefer-localhost-replica)

Many of these unlock potential optimizations by streaming less data over the network, but require data to be sharded correctly to work.

## Ad-hoc distributed queries

It's sometimes useful to query data from across the cluster without setting up Distributed tables, for example to query system tables on all nodes or shards.

This can be done as such:

```sql runInPostHog=false
SELECT hostName(), shardNum(), *
FROM clusterAllReplicas('my_cluster', 'system', 'metrics')
```

More documentation on this can be found at:
- [cluster, clusterAllReplicas ClickHouse docs](https://clickhouse.com/docs/en/sql-reference/table-functions/cluster/)
- [Other Functions ClickHouse docs](https://clickhouse.com/docs/en/sql-reference/functions/other-functions/)

## Further reading

- [Data Replication ClickHouse docs](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replication/)
- [Strength in Numbers: Introduction to ClickHouse Cluster Performance](https://altinity.com/presentations/strength-in-numbers-introduction-to-clickhouse-cluster-performance)
- [Engines](https://kb.altinity.com/engines/)
- [ZooKeeper schema](https://kb.altinity.com/altinity-kb-setup-and-maintenance/altinity-kb-zookeeper/zookeeper-schema/)

Next in the ClickHouse manual: [Data ingestion](/handbook/engineering/clickhouse/data-ingestion)
