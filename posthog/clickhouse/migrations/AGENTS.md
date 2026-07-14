PostHog ClickHouse setup

# Cluster setup

## Environments

There are 3 environments:

- Development
- US Production
- EU Production

## US Production

The main clusters are:

- 30 worker nodes (10x3)
  - 10 shards
  - 3 replicas
- ai_events 1x2
- aux 1x2
- sessions 1x2
- ops 1x2

## EU Production

The main cluster is:

- 24 worker nodes - all tables are defined on worker nodes
  - 8 shards
  - 3 replicas

Additionally, on k8s we have stateless nodes:

## ShuffleHog nodes

It shuffles data between Kafka partitions.

## Ingestion nodes

It ingests data from Kafka to a proper ClickHouse shard.
Ingestion nodes are part of the extended ClickHouse cluster

The way this is done:

1. Create a writeable table, this is a Distributed engine table
2. Create a table with the Kafka engine
3. Create a materialized view that reads from Kafka and writes to the writetable table

If a destination table is non-sharded, we pick only one node as data for the Distributed table.

# Local setup parity

No table should exist only in the cloud. Every table created via migration must also exist
in a local dev environment.

Some migrations are cloud-guarded and skipped in local/hobby dev:

```python
operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [...]
)
```

If you create a new table inside such a guard, also add its SQL function to
`posthog/clickhouse/schema.py` in the appropriate tuple so the table is created locally:

| Table type             | Tuple in `schema.py`               |
| ---------------------- | ---------------------------------- |
| MergeTree / base table | `CREATE_MERGETREE_TABLE_QUERIES`   |
| Distributed / writable | `CREATE_DISTRIBUTED_TABLE_QUERIES` |
| Kafka consumer         | `CREATE_KAFKA_TABLE_QUERIES`       |
| Materialized view      | `CREATE_MV_TABLE_QUERIES`          |
| Non-materialized view  | `CREATE_VIEW_QUERIES`              |
| Dictionary             | `CREATE_DICTIONARY_QUERIES`        |

The only exception is tables whose definition intentionally differs per environment and is
not tracked in the repo (e.g. the no-go zone `events_json_ws_mv` table above).

# Migration basics

## run_sql_with_exceptions function

All migrations use `run_sql_with_exceptions(sql, node_roles=[], sharded=False, is_alter_on_replicated_table=False)`:

Parameters:

- `sql`: SQL string to execute (can be a function call returning SQL)
- `node_roles`: List of NodeRole values (default: `[NodeRole.DATA]` if not specified)
  - `[NodeRole.DATA]`: Data/worker nodes
  - `[NodeRole.INGESTION_SMALL]`: Ingestion layer nodes
  - `[NodeRole.ALL]`: Rarely used, all nodes
- `sharded`: Set to `True` when operating on sharded tables (ensures one operation per shard)
- `is_alter_on_replicated_table`: Set to `True` for ALTER on replicated tables (runs on one host per shard)

## Table engines

### MergeTree engines (from table_engines.py)

All MergeTree engines accept:

- `table`: Table name (required)
- `replication_scheme`: Enum value (default: `ReplicationScheme.REPLICATED`)
  - `ReplicationScheme.NOT_SHARDED`: Single node, no replication
  - `ReplicationScheme.SHARDED`: Sharded + replicated
  - `ReplicationScheme.REPLICATED`: Replicated but not sharded (noshard in ZK path)

Available engines:

- `MergeTreeEngine(table, replication_scheme=...)`
- `ReplacingMergeTree(table, replication_scheme=..., ver=...)`: For deduplication
- `ReplacingMergeTreeDeleted(table, replication_scheme=..., ver=..., is_deleted=...)`: With deletion tracking
- `CollapsingMergeTree(table, replication_scheme=..., ver=...)`: For collapsing rows
- `AggregatingMergeTree(table, replication_scheme=...)`: For aggregated data

Example:

```python
engine=AggregatingMergeTree(
    "sharded_events",
    replication_scheme=ReplicationScheme.SHARDED
)
```

### Distributed engine

`Distributed(data_table, sharding_key=None, cluster=None)`:

- `data_table`: Name of underlying sharded/local table (required)
- `sharding_key`: Expression like `"sipHash64(person_id)"` (optional, omit for non-sharded)
- `cluster`: Override cluster (default: `settings.CLICKHOUSE_CLUSTER`)
  - Use `cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER` for non-sharded tables to point to single shard

Examples:

```python
# Sharded distributed table
engine=Distributed(
    data_table="sharded_events",
    sharding_key="sipHash64(person_id)",
    cluster=CLICKHOUSE_CLUSTER
)

# Non-sharded distributed table (for ingestion layer)
engine=Distributed(
    data_table="person_distinct_id2",
    cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER
)
```

# General rules

> [!CAUTION]
> Do not use `ON CLUSTER` clause, it causes issues and is incompatible with our migration setup.

> [!CAUTION]
> Never write a `DROP COLUMN` migration on your own. `DROP COLUMN` can get stuck in ClickHouse
> and block releases. Column removal follows a two-step process:
>
> 1. The ClickHouse team drops the column directly on the cluster.
> 2. You write a migration with the matching `DROP COLUMN` to keep the codebase schema in sync.
>
> Do not initiate step 2 without confirmation that step 1 has been completed.

> [!INFO]
> Always use `IF EXISTS` / `IF NOT EXISTS` guards. For `ALTER TABLE` the guard goes on the
> operation, **not** on the table — `ALTER TABLE IF EXISTS ...` is a ClickHouse syntax error.
>
> `CREATE TABLE IF NOT EXISTS my_table ...`
>
> `ALTER TABLE my_table ADD COLUMN IF NOT EXISTS my_col ...`
>
> `ALTER TABLE my_table MODIFY COLUMN IF EXISTS my_col ...`
>
> `ALTER TABLE my_table DROP COLUMN IF EXISTS my_col`

> [!CAUTION]
> Never drop or recreate `kafka_events_json_ws` or `events_json_ws_mv`. These tables are a
> no-go zone. The MV definition differs between US prod, EU prod, and dev (dozens of
> environment-specific `mat_*` materialized columns) and those differences are **not reflected
> in the repo**. Dropping and recreating from repo SQL would destroy the environment-specific
> schema and break event ingestion. Any change must go through the ClickHouse team.

> [!INFO]
> A PR containing a ClickHouse migration must be migration-only. Do not mix it with feature code,
> API changes, model changes, or frontend changes. Migration-related files are:
>
> - The migration file itself (`posthog/clickhouse/migrations/0NNN_*.py`)
> - SQL definition files the migration depends on (e.g. `posthog/clickhouse/sql/*.py`)
> - Tests that directly exercise the migration or the SQL definitions it touches
>
> If application code needs the new schema, ship the migration PR first and merge it before
> the application-code PR.

# CREATE / DROP patterns

## Replicated, non-sharded tables

Engine: `ReplacingMergeTree(table, replication_scheme=ReplicationScheme.REPLICATED)` (or other MergeTree variant)

Migration:

```python
run_sql_with_exceptions(
    TABLE_SQL(),
    node_roles=[NodeRole.DATA]
)
```

The table is created on data nodes because it's not sharded.

## Replicated, sharded tables

Engine: `AggregatingMergeTree(table, replication_scheme=ReplicationScheme.SHARDED)` (or other MergeTree variant)

Migration:

```python
run_sql_with_exceptions(
    SHARDED_TABLE_SQL(),
    node_roles=[NodeRole.DATA]
)
```

The table is created only on data nodes because sharding only applies to worker nodes.

## Distributed tables (read path)

Engine: `Distributed(data_table, sharding_key=...)`

Migration:

```python
run_sql_with_exceptions(
    DISTRIBUTED_TABLE_SQL(),
    node_roles=[NodeRole.DATA]
)
```

Created on data nodes so queries can be executed from them.

## Distributed tables (write path / writable)

Engine: `Distributed(data_table, sharding_key=...)`

For main cluster ingestion (legacy):

```python
run_sql_with_exceptions(
    WRITABLE_TABLE_SQL(),
    node_roles=[NodeRole.DATA]
)
```

For ingestion layer (new pattern):

```python
run_sql_with_exceptions(
    WRITABLE_TABLE_SQL(),
    node_roles=[NodeRole.INGESTION_SMALL]
)
```

## Kafka tables

For main cluster (legacy/being deprecated):

```python
run_sql_with_exceptions(
    KAFKA_TABLE_SQL(),
    node_roles=[NodeRole.DATA]
)
```

For ingestion layer (recommended):

```python
run_sql_with_exceptions(
    KAFKA_TABLE_SQL(),
    node_roles=[NodeRole.INGESTION_SMALL]
)
```

## Materialized views

For main cluster (legacy):

```python
run_sql_with_exceptions(
    MV_SQL(),
    node_roles=[NodeRole.DATA]
)
```

For ingestion layer (recommended):

```python
run_sql_with_exceptions(
    MV_SQL(),
    node_roles=[NodeRole.INGESTION_SMALL]
)
```

## Views (non-materialized)

```python
run_sql_with_exceptions(
    VIEW_SQL(),
    node_roles=[NodeRole.DATA]
)
```

## Dictionaries

```python
run_sql_with_exceptions(
    DICTIONARY_SQL(),
    node_roles=[NodeRole.DATA]
)
```

# Recreating tables

If a replicated table is to be deleted and created again in the same migration, use `DROP TABLE IF EXISTS ... SYNC`:

```sql
DROP TABLE IF EXISTS my_table SYNC
```

The `SYNC` modifier ensures the drop completes before the subsequent CREATE runs - this is necessary becasue replicated table keeps
some metadata in ZooKeeper.

SYNC is not necessary for non-replicated objects: Kafka table engine, Distributed table engine or MATERIALIZED VIEW.

# ALTER operations

## Non-sharded replicated tables

```python
run_sql_with_exceptions(
    "ALTER TABLE my_table ADD COLUMN IF NOT EXISTS ...",
    node_roles=[NodeRole.DATA],
    is_alter_on_replicated_table=True
)
```

The `is_alter_on_replicated_table=True` flag ensures the ALTER runs on one host only (replication propagates it).

## Sharded tables

```python
run_sql_with_exceptions(
    "ALTER TABLE sharded_my_table ADD COLUMN IF NOT EXISTS ...",
    node_roles=[NodeRole.DATA],
    sharded=True
)
```

The `sharded=True` flag ensures the ALTER runs once per shard.

## Distributed tables

```python
run_sql_with_exceptions(
    "ALTER TABLE distributed_my_table ADD COLUMN IF NOT EXISTS ...",
    node_roles=[NodeRole.DATA]
)
```

Runs on data nodes because distributed tables exist on data nodes.

# Ingestion layer pattern

The recommended pattern for new tables uses dedicated ingestion nodes. This separates ingestion load from query load.

Complete pattern:

1. Create data table on the main cluster (DATA nodes)
2. Create writable distributed table on ingestion nodes with `CLICKHOUSE_SINGLE_SHARD_CLUSTER` for non-sharded tables
3. Create a Kafka table on ingestion nodes
4. Create a materialized view on ingestion nodes

Example for non-sharded table:

```python
operations = [
    # 1. Data table on main cluster
    run_sql_with_exceptions(
        DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA]
    ),
    # 2. Writable distributed table on ingestion layer
    run_sql_with_exceptions(
        WRITABLE_TABLE_SQL(),  # Uses cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER
        node_roles=[NodeRole.INGESTION_SMALL]
    ),
    # 3. Kafka table on ingestion layer
    run_sql_with_exceptions(
        KAFKA_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL]
    ),
    # 4. Materialized view on ingestion layer
    run_sql_with_exceptions(
        MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL]
    ),
]
```

See migration 0153 for a complete example.
