---
name: clickhouse-migrations
description: ClickHouse migration patterns and rules. Use when creating or modifying ClickHouse migrations.
---

# ClickHouse Migrations

Read `posthog/clickhouse/migrations/AGENTS.md` for comprehensive patterns, cluster setup, examples, and ingestion layer details.

## Quick reference

### Migration structure

```python
operations = [
    run_sql_with_exceptions(
        SQL_FUNCTION(),
        node_roles=[...],
        sharded=False,  # True for sharded tables
        is_alter_on_replicated_table=False  # True for ALTER on replicated tables
    ),
]
```

### Node roles (choose based on table type)

- `[NodeRole.DATA]`: Sharded tables (data nodes only)
- `[NodeRole.DATA, NodeRole.COORDINATOR]`: Non-sharded data tables, distributed read tables, replicated tables, views, dictionaries
- `[NodeRole.INGESTION_SMALL]`: Writable tables, Kafka tables, materialized views on ingestion layer

### Table engines quick reference

MergeTree engines:

- `AggregatingMergeTree(table, replication_scheme=ReplicationScheme.SHARDED)` for sharded tables
- `ReplacingMergeTree(table, replication_scheme=ReplicationScheme.REPLICATED)` for non-sharded
- Other variants: `CollapsingMergeTree`, `ReplacingMergeTreeDeleted`

Distributed engine:

- Sharded: `Distributed(data_table="sharded_events", sharding_key="sipHash64(person_id)")`
- Non-sharded: `Distributed(data_table="my_table", cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER)`

### Critical rules

- NEVER use `ON CLUSTER` clause in SQL statements
- Always use `IF EXISTS` / `IF NOT EXISTS` clauses
- When dropping and recreating replicated table in same migration, use `DROP TABLE IF EXISTS ... SYNC`
- If a function generating SQL has on_cluster param, always set `on_cluster=False`
- Use `sharded=True` when altering sharded tables
- Use `is_alter_on_replicated_table=True` when altering non-sharded replicated tables
- **Never write a `DROP COLUMN` migration yourself** — `DROP COLUMN` can get stuck in ClickHouse and block releases. Column removal is a two-step process: (1) the ClickHouse team drops the column directly on the cluster, then (2) you write a migration with the matching `DROP COLUMN` so the codebase schema stays in sync. Never initiate the drop from a migration without the ClickHouse team having done step 1 first.
- **Never drop or recreate `kafka_events_json_ws` or `events_json_ws_mv`** — these tables are a no-go zone. The MV definition differs significantly between US prod, EU prod, and dev (dozens of environment-specific `mat_*` columns) and those differences are **not reflected in the repo**. Dropping and recreating from repo SQL would destroy the environment-specific schema and break event ingestion. Any change must go through the ClickHouse team.

### PR scope

A PR that contains a ClickHouse migration **must be migration-only**. Do not mix migration files with feature code, API changes, model changes, or frontend changes in the same PR. Migration-related files are:

- The migration file itself (`posthog/clickhouse/migrations/0NNN_*.py`)
- SQL definition files the migration depends on (e.g. `posthog/clickhouse/sql/*.py`, table engine helpers)
- Tests that directly exercise the migration or the SQL definitions it touches

If you need both a schema change and application code that uses the new schema, ship the migration first in its own PR and merge it before the application-code PR.

### Local setup parity

**No table should exist only in the cloud.** Every table created via migration must also exist in a local dev environment.

Some migrations are cloud-guarded and skipped in local/hobby dev:

```python
operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [...]
)
```

If you create a new table inside such a guard, you must also add its SQL function to `posthog/clickhouse/schema.py` in the appropriate tuple so the table gets created locally:

| Table type             | Tuple in `schema.py`               |
| ---------------------- | ---------------------------------- |
| MergeTree / base table | `CREATE_MERGETREE_TABLE_QUERIES`   |
| Distributed / writable | `CREATE_DISTRIBUTED_TABLE_QUERIES` |
| Kafka consumer         | `CREATE_KAFKA_TABLE_QUERIES`       |
| Materialized view      | `CREATE_MV_TABLE_QUERIES`          |
| Non-materialized view  | `CREATE_VIEW_QUERIES`              |
| Dictionary             | `CREATE_DICTIONARY_QUERIES`        |

The only exception is tables whose definition intentionally differs per environment and is not tracked in the repo (e.g. the no-go zone `events_json_ws_mv` table).

**Dictionary credentials:** when a dictionary uses a `SOURCE(CLICKHOUSE(...))`, resolve the source user/password via `get_clickhouse_creds(ClickHouseUser.DICT_READER)` and interpolate them into the `USER`/`PASSWORD` clause — do not hardcode `default`/`CLICKHOUSE_USER` or omit credentials. This keeps dictionary auth on the dedicated low-privilege `dict_reader` user, decoupled from `default`; it falls back to `default` creds when the env vars are unset. See `posthog/models/exchange_rate/sql.py` for the pattern.

### Testing

Delete entry from `infi_clickhouse_orm_migrations` table to re-run a migration.
