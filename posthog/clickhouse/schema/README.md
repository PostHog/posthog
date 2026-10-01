# ClickHouse schema

The ClickHouse schema is declared here as OpenTofu configuration.
There are no migrations: you change the declaration, and OpenTofu works out the `CREATE` and `ALTER` statements that get a server from what it has to what is declared.

```text
schema/
  modules/<group>/   # one module per group of related objects (events, person, logs, ...)
  lib/               # one helper module per object kind; each group is built from these
  local/             # root module: every group on one server
  provider-version.txt
```

## Groups and components

A group holds the objects that belong to one table family.
`modules/events`, for example, has the sharded data table, the Distributed tables that read from it and write to it, the Kafka table and the materialized view that fills it.

Each object is in one component of its group:

| Component | What is in it                                                          |
| --------- | ---------------------------------------------------------------------- |
| `storage` | Tables that hold data, and the materialized views between them         |
| `read`    | Distributed tables, views and dictionaries that queries read from      |
| `write`   | Distributed tables that inserts go through                             |
| `ingest`  | Kafka tables and the materialized views that consume them              |
| `test`    | Objects only the test suite uses, for example views that replace Kafka |

Components exist because a group does not live on one node in production.
The storage tables are on the data nodes, the Kafka tables on the ingestion nodes, and the Distributed tables on every cluster that queries the group.
A root module says which components of which groups go on which nodes.

## What this repository owns

This repository owns the groups, the definitions, and one root: `local/`, which puts every component of every group on a single server.
That root is what local development, tests, CI and self-hosted installs use.

Which clusters and nodes get which components in PostHog Cloud is not decided here.
The infrastructure repository has one root per cluster.
Each root takes these modules from `master` and passes three things:

- `components`: the parts of the group that cluster has.
- `exclude`: objects of those components that cluster does not have.
- `overrides`: per-object changes, for a cluster whose definition differs from the one here (a different sorting key, a storage policy, extra columns, a Distributed table that points at another cluster).

`lib/table/main.tf` lists the override keys for tables.
Views, materialized views and dictionaries accept the arguments of their `lib` module as keys.

Objects that exist only in PostHog Cloud are declared in the infrastructure repository, not here.

## Changing the schema

1. Edit the module of the group. Column lists that several objects use are in `columns.tf` of the module, so a new column usually goes in one place.
2. Write expressions the way ClickHouse prints them in `SHOW CREATE TABLE`. The provider compares your text with what the server reports and ignores only whitespace, so `x::Date` instead of `CAST(x, 'Date')` shows up as a change on every plan. The exception is text inside a quoted string, such as the `QUERY` of a dictionary source: ClickHouse stores that as written.
3. A new object goes in the file of its component. A new group is a new directory under `modules/` and a `module` block in `local/modules.tf`.
4. Run `bin/clickhouse-schema plan` to see the statements, then `bin/clickhouse-schema apply`.

A pull request that changes this directory gets applied to a fresh ClickHouse in CI, and a second plan must come back empty.
After the merge, the infrastructure repository is told about the new commit and plans the change for each cluster, where it is reviewed and applied.

What the provider does with a change:

| Change                                                                   | Statement                                   |
| ------------------------------------------------------------------------ | ------------------------------------------- |
| Add, change or remove a column, index, projection, constraint or setting | `ALTER TABLE`, in place                     |
| Change the query of a materialized view with a target table              | `ALTER TABLE ... MODIFY QUERY`              |
| Change a view or a dictionary                                            | `CREATE OR REPLACE`                         |
| Change `engine`, `partition_by`, `primary_key`, or reorder `order_by`    | Drop and recreate, which **loses the data** |
| Change a Kafka table                                                     | Drop and recreate                           |

Read the plan before you apply it.
`must be replaced` is routine for Kafka and Distributed tables, which hold no data.

The provider refuses to drop or replace a MergeTree-family table that holds rows on any node, and the plan fails with `Refusing to replace`.
If losing the data is intended, apply `force_destroy = true` in the table's `override` on its own first; the next plan can then drop it.

A change that rewrites data, such as a column type change, starts a mutation.
The apply does not wait for it: it checks for a few seconds that the mutation runs, and reports one that is still running as a warning.
A mutation that fails stops the apply, and fails every later plan of that table until it is fixed or stopped with `KILL MUTATION`.

## Reference data

A small table whose rows never change at runtime declares them with `clickhousedbops_table_contents`, next to the table, from a file in the module directory.
The plan shows a change when the rows on any node differ from the file, and the apply swaps the new rows in without an empty moment.
`channel_definition` (from `channel_definitions.json`) and `web_bot_definition` (from `web_bot_definitions.jsonl`, which `python manage.py write_bot_definitions_file` writes from `BOT_DEFINITIONS`) work this way.
Both are plain `MergeTree` tables on every node that has their dictionary, with `force_destroy` and `ignore_drop_dependencies` set, so a definition change recreates them in place under their dictionaries.
Tables that a job refreshes, such as `exchange_rate`, do not declare their rows.

Dictionaries that read from ClickHouse take their user and password from the `dictionary_user` and `dictionary_password` variables of the module. Do not write a password in a dictionary source.

## Running it

`bin/clickhouse-schema` downloads OpenTofu and the provider on first use and runs OpenTofu on `local/`.
It checks each download against the sha256 that `checksums.txt` pins, and lets OpenTofu install no provider but `posthog/clickhousedbops`.
A new provider or OpenTofu version needs its lines in `checksums.txt`, from the release's `SHA256SUMS`.
It reads the connection from the same `CLICKHOUSE_*` variables the app reads.

```bash
bin/clickhouse-schema plan     # show what apply would do
bin/clickhouse-schema apply    # create or update every object
```

`bin/migrate --scope=clickhouse` and `python manage.py apply_clickhouse_schema` create the database, call the script and load the reference data.
The test suite builds its databases the same way, with `CLICKHOUSE_SCHEMA_KAFKA=false` and `CLICKHOUSE_SCHEMA_TEST=true`.

No state is committed.
The script keeps the OpenTofu state of each target under `~/.cache/posthog-clickhouse-schema`, and the provider adopts objects that already exist, so a lost state costs nothing.

To work on the provider itself, set `CLICKHOUSE_SCHEMA_PROVIDER_SRC` to a checkout of it and the script builds the provider from there.
