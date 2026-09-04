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

### Node roles (choose by the cluster that owns the object)

Only the members of `NodeRole` in `posthog/clickhouse/client/connection.py` are valid: `ALL`, `DATA`,
`INGESTION_EVENTS`, `INGESTION_SMALL`, `INGESTION_MEDIUM`, `ENDPOINTS`, `LOGS`, `AI_EVENTS`, `AUX`,
`BATCH_EXPORTS`, `OPS`, `SESSIONS`. A name that is not in that enum fails at import, which aborts
migration discovery and takes every job that runs migrations down with it.

Pick the role by **which cluster owns the object**, not by its type alone:

- `[NodeRole.DATA]`: anything on the main cluster — sharded tables, non-sharded replicated tables,
  distributed read tables, views, dictionaries. The default, and right for most migrations.
- `[NodeRole.INGESTION_SMALL]`: writable tables, Kafka tables, materialized views on the ingestion layer
- `[NodeRole.OPS]`, `[NodeRole.LOGS]`, `[NodeRole.AUX]`, `[NodeRole.AI_EVENTS]`, `[NodeRole.SESSIONS]`,
  `[NodeRole.BATCH_EXPORTS]`: objects that live on a satellite cluster. A table for one of those on
  `DATA` lands on the wrong nodes and leaves the intended cluster without it, so check where the
  object is read and written before defaulting to `DATA`. Dev runs the same satellite clusters as
  US/EU prod — never branch on `CLOUD_DEPLOYMENT` to give dev a different layout.
- `[NodeRole.ALL]`: rarely used

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
- **Never write `CODEC(ZSTD(1))` on a column** — the server already compresses every column with ZSTD, so it buys nothing. Declare a CODEC only where it beats that default, and check the `ORDER BY` first: `Delta`/`DoubleDelta` need the column near-sorted in storage order (a leading sort-key prefix), and lose on a column the key only buckets or omits. `T64`/`Gorilla` are ordering-independent. Put it on the storage table only — a CODEC on a Distributed or Kafka table is inert metadata that drifts from the sharded table it fronts.
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

Some migrations are cloud-guarded and skipped in local/hobby dev. Gate on `posthog.run_mode`, never on `settings.CLOUD_DEPLOYMENT` directly, because the `clickhouse-migrations-use-run-mode` semgrep rule blocks raw comparisons:

```python
from posthog.run_mode import RunMode, run_mode

operations = (
    []
    if not run_mode().is_deployed_cloud  # US/EU/DEV
    else [...]
)
```

| Predicate                        | True for                                      |
| -------------------------------- | --------------------------------------------- |
| `run_mode().is_deployed_cloud`   | US, EU, DEV (the usual migration gate)        |
| `run_mode().is_prod_cloud`       | US, EU (excludes staging)                     |
| `run_mode() is RunMode.CLOUD_US` | one region (`CLOUD_EU`, `CLOUD_DEV` likewise) |

`run_mode().is_cloud` also counts E2E, so it is wrong for a migration. That one matches `posthog.cloud_utils.is_cloud`.

Call `run_mode()` where you need it rather than assigning a module-level constant. `posthog/clickhouse/test/test_migrations.py` re-imports every migration under a patched `posthog.settings.CLOUD_DEPLOYMENT` to check each deployment's branch for stray `ON CLUSTER`, and a cached value would silently skip that coverage.

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

### Declarative schema (HCL) must agree

Some roles are also declared in `posthog/clickhouse/hcl/`, and the multinode migration smoke re-introspects
the migrated cluster and fails on any drift between the live schema and the committed golden. A table added
by a migration on a managed role therefore needs the HCL updated in the same PR, or CI fails at
`check_live_hcl` with a `DRIFT:` block naming your new objects.

The `data` role is managed for the `local-multi` composition, so a new table on `NodeRole.DATA` counts.
After writing the migration:

```sh
HCL=posthog/clickhouse/hcl
# add the table to the layer that composes it, e.g. $HCL/roles/data/local/tables.hcl
bash $HCL/gen-golden.sh && bash $HCL/gen-sql.sh   # refresh generated artifacts
bash $HCL/check.sh                                # must exit 0
```

Read `posthog/clickhouse/hcl/README.md` before editing a layer — it covers which layer to pick, abstract
column lists, and the codegen path that writes the migration for you.

### Testing

Delete entry from `infi_clickhouse_orm_migrations` table to re-run a migration.
