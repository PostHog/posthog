---
name: clickhouse-migrations
description: >
  Rules and workflow for changing the ClickHouse schema, which is declared as OpenTofu configuration in `posthog/clickhouse/schema/`.
  Use when changing the ClickHouse schema: adding or altering a table, column, index, projection, materialized view, Kafka table, or dictionary, or editing anything under `posthog/clickhouse/schema/`.
  Covers where each object lives, how to pick the group and component for a new object, shared column lists, writing expressions in ClickHouse's canonical form, reading the plan for replacements that lose data, the cloud rollout from the infrastructure repository, and the safety rules (no `DROP COLUMN` without the ClickHouse team, the `events_json_ws` no-go zone, codecs, Kafka table settings, PR scope).
  Trigger terms: ClickHouse migration, ClickHouse schema, clickhouse-schema plan, add column, skip index, Kafka table, materialized view.
---

# Changing the ClickHouse schema

There are no ClickHouse migrations.
The schema is declared as OpenTofu configuration, and the provider works out the `CREATE` and `ALTER` statements.
Read [`posthog/clickhouse/schema/README.md`](../../../posthog/clickhouse/schema/README.md) first. It is the source of truth, and this skill only adds the rules around it.

## Where things live

```text
posthog/clickhouse/schema/
  modules/<group>/   # one module per table family
    main.tf          # which components the group has
    variables.tf     # database, components, exclude, overrides, zk_path_suffix
    columns.tf       # column lists that more than one object uses
    storage.tf  read.tf  write.tf  ingest.tf  test.tf   # one file per component
  lib/               # table, view, materialized_view, dictionary helpers
  local/             # root module: every group on one server
```

Each object is one `module` block that calls a `lib` helper.
`modules/person` is a small, complete group to copy from. `modules/events` is the sharded equivalent.

## Pick the group and the component

A group is one table family.
Add the object to the group of the table it stores, reads, or fills.
Make a new group only for a new table family, and add a `module` block for it to `local/modules.tf`.

The component decides which nodes get the object in PostHog Cloud, so choose it by what the object does:

| Object                                                          | Component | File         |
| --------------------------------------------------------------- | --------- | ------------ |
| MergeTree table, or a materialized view between storage tables  | `storage` | `storage.tf` |
| Distributed table, view, or dictionary that queries read        | `read`    | `read.tf`    |
| Distributed table that inserts go through (`writable_*`)        | `write`   | `write.tf`   |
| Kafka table, or the materialized view that consumes it          | `ingest`  | `ingest.tf`  |
| Object only the test suite uses, such as a view replacing Kafka | `test`    | `test.tf`    |

Every object follows the same shape, from `modules/person/write.tf`:

```hcl
module "writable_person" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_person")
  database = var.database
  name     = "writable_person"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'person')"
  columns  = local.person_columns
  override = try(var.overrides["writable_person"], {})
}
```

Keep the `enabled` and `override` lines exactly in this form. The infrastructure repository relies on them to leave an object out of a cluster or to change it there.
Use `${var.database}` for the database name, and `${var.zk_path_suffix}` in every replication path.
Add `depends_on` when an object reads from or writes to another one, as `person_mv` does.

A table that only exists in PostHog Cloud is not declared here. It belongs in the infrastructure repository.
Everything declared here is created locally and in tests too.

## Add a column

1. Find the column list. If `columns.tf` has one for the table, add the column there. `modules/person/columns.tf` builds `person_columns` from `kafka_person_columns`, so one line reaches the Kafka table, the writable table, and the storage table.
2. If a table declares its columns inline, add the column to each table that needs it: the storage table, the Distributed tables in front of it, and the Kafka table when the value comes from the topic.
3. Add the column to the `SELECT` of the materialized view that fills the table.
4. For a materialized column, put `materialized_expression` on the storage table. The Distributed table in front of it declares the plain column, as `events` does for the `$group_0` column of `sharded_events`.

## Write expressions in canonical form

The provider compares your text with what the server reports and ignores only whitespace.
Write every expression the way `SHOW CREATE TABLE` prints it, or the plan shows a change on every run.

- `CAST(x, 'Date')`, not `x::Date`.
- `toIntervalDay(90)`, not `INTERVAL 90 DAY`.
- Full type names with their arguments: `DateTime64(6, 'UTC')`, `Decimal(18, 10)`.
- Settings the server adds, such as `index_granularity = 8192`.

The check is a second plan: run `bin/clickhouse-schema apply`, then `bin/clickhouse-schema plan`. The second plan must be empty.
If it is not, copy the text from `SHOW CREATE TABLE` into the declaration.

## Read the plan

```bash
bin/clickhouse-schema plan     # show the statements
bin/clickhouse-schema apply    # run them against local ClickHouse
```

`update in-place` is an `ALTER`. `must be replaced` is a drop and a recreate.

- A replacement of a table that holds data loses the data. A change to `engine`, `partition_by`, or `primary_key`, or a reorder of `order_by`, causes one. Stop and ask the ClickHouse team how to get there without a replacement.
- A replacement of a Kafka table is expected. Any change to one replaces it, and it holds no data.
- A plan that still shows a change right after an apply means an expression is not in canonical form.

## Rollout

CI applies the change to a fresh ClickHouse and fails if a second plan is not empty.
After the merge, the infrastructure repository plans the change for each cloud cluster, and the change is reviewed and applied there.
The app deploy does not apply the schema in PostHog Cloud.

Two consequences:

- **A schema change ships in its own PR, and merges before the code that depends on it.** The PR holds the `.tf` change and, at most, tests of the schema. Feature code that reads or writes the new object goes in a later PR, after the change is applied in cloud.
- **A change must work with the code that is already deployed.** Add before you use. Stop using before you remove.

A cluster whose definition differs from this repository gets its difference through `overrides` in the infrastructure repository. Do not add per-environment branches here.

## Safety rules

- **Never remove a column without the ClickHouse team.** `DROP COLUMN` can get stuck in ClickHouse. The ClickHouse team drops the column on the clusters first, and only then does a PR remove it from the declaration.
- **Never drop or recreate `kafka_events_json_ws` or `events_json_ws_mv`.** They differ between US, EU, and dev, and they are not declared in this repository. Any change to them goes through the ClickHouse team.
- **Do not put `ZSTD(1)` on a column.** The server already compresses every column with ZSTD. Declare a `codec` only where it beats that default. `Delta` and `DoubleDelta` need the column near-sorted in storage order, which means a leading `order_by` prefix. `T64` and `Gorilla` do not depend on the order. Pair a specialized codec with ZSTD as the second stage, for example `DoubleDelta, ZSTD(1)`.
- **Put a new codec on the storage table only.** A codec on a Distributed or Kafka table does nothing.
- **Never write a password in a dictionary source.** A dictionary that needs credentials takes them from the `dictionary_user` and `dictionary_password` variables, as `modules/dmat_slot_assignments` does.

## Kafka tables

Settings go in the `settings` string of the table, in alphabetical order like the existing tables.
Start a new Kafka table from these values and change one only for a reason:

```text
kafka_max_block_size = 100000, kafka_num_consumers = 1, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1
```

- `kafka_skip_broken_messages` defaults to 0, and then one malformed message stops the consumer for good. Set it on every table.
- `kafka_poll_timeout_ms` is 10000 because WarpStream does not support `fetch.min.bytes`, so a short timeout gives many small fetches.
- `kafka_max_block_size` is the row count of one insert into the target table. The default is about a million rows. Go lower than 100000 for wide rows, and stay above about 1000.
- `kafka_num_consumers` is per node. The total across all nodes that have the table must not exceed the number of partitions of the topic.
- Leave `kafka_flush_interval_ms` unset.

Any change to a Kafka table replaces it. The offsets belong to the consumer group, so keep `kafka_group_name` and the cost is lag, not loss.
A change to the `query` of a materialized view is a `MODIFY QUERY` and replaces nothing.
Rows already written keep the old shape, so a change to how a column is derived needs a backfill.

## Before you open the PR

- `bin/clickhouse-schema apply`, then `bin/clickhouse-schema plan` comes back empty.
- The plan for your change has no replacement of a table that holds data.
- The PR holds the schema change only.
