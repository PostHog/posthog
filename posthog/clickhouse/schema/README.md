# ClickHouse schema

The ClickHouse schema is declared here as OpenTofu configuration.
There are no migrations: you change the declaration, and OpenTofu works out the `CREATE` and `ALTER` statements that get a server from what it has to what is declared.

```text
schema/
  catalog/           # simple table-family declarations, shared by local and cloud roots
  catalog/<group>/main.tf  # one file for columns, families and custom objects
  lib/               # one helper module per object kind; each group is built from these
  local/             # root module: every group on one server
  provider-version.txt
```

## Staged rollout

This catalogue is additive during the foundation stage. Existing Python migrations, HCL checks, test setup and Hobby initialization remain the active paths. Run `bin/clickhouse-schema` only against a dedicated test database until ownership cutover.

The companion infrastructure canary adopts only `dev/ops/custom_metrics_test`. Adoption must issue no DDL; a later schema-only pull request changes its help text to prove dispatch, reviewed planning and apply. The current Python definitions remain authoritative for all other objects.

Switch local, test and Hobby setup only after the cloud handover is verified. Delete the legacy implementations in a separate cleanup pull request.

## Standard table families

Add a `.tf` file under `catalog/` for a standard sharded or global table family.
Every local and cloud root calls that catalogue, so a new family needs no per-cluster wiring.
The calling root lists the objects it wants; the declaration supplies the topic, columns, storage keys and ingestion transformation.
`catalog/billing_usage_records.tf` is a complete sharded example and `catalog/property_definitions.tf` is a global example.

```hcl
module "example_events" {
  source = "../lib/table_family"

  name     = "example_events"
  database = var.database
  columns  = local.example_stored_columns
  storage = {
    order_by     = "(team_id, timestamp)"
    partition_by = "toYYYYMM(timestamp)"
    indexes      = local.example_indexes
    projections  = local.example_projections
  }
  kafka = {
    topic   = "example_events"
    columns = local.example_input_columns
  }
  mv_select  = "team_id, timestamp, value"
  deployment = merge(var.deployment.sharded, try(var.deployment.families.example_events, {}))
}
```

`table_family` declares `sharded_<name>`, `<name>`, `writable_<name>`, `kafka_<name>` and `<name>_mv`, and creates the ones the root lists. Omit `kafka` and `mv_select` for a family without Kafka ingestion.
`storage.engine` defaults to `MergeTree`; set `ReplacingMergeTree` and `engine_args = ["version"]` for versioned rows. The library supplies replication arguments.
`sharding_key` defaults to `cityHash64(team_id)` and can be changed explicitly. A standalone family defaults to aux routing; a global family defaults to posthog routing.
The materialized view's `mv_select` is the expression list after `SELECT`; the library supplies its Kafka `FROM` and writable `TO`. More complex queries can use an explicit MV `query` override or the low-level helper.

Indexes, projections, constraints, codecs, column TTLs and computed expressions belong to storage. Readers expose computed values as plain columns; writers expose insertable columns. Kafka has its own input columns. The library rejects index, projection and constraint overrides unless the target uses a MergeTree engine. Existing routing schemas can explicitly retain computed expressions.
Kafka defaults use one consumer, a 100000-row maximum block, a 10000ms poll timeout, 100 skipped broken messages and one thread per consumer. A supplied `kafka.settings` map replaces these defaults; values are SQL expressions, for example `date_time_input_format = "'best_effort'"`. Existing families preserve their existing settings and consumer groups. Billing retains its local Kafka engine/SETTINGS spelling through a deployment override; changing that spelling would otherwise replace the consumer table. Retire this exception only in an explicit Kafka change that preserves its consumer group.

Kafka topic namespaces come from deployment: `kafka_topic_prefix` and `kafka_topic_suffix` apply to every topic in a Kafka table's `kafka_topic_list`, including explicit table overrides. Local setup reads `KAFKA_PREFIX`; tests add `_test` to match the application producers. Production defaults leave topics unchanged. Explicit Kafka tables pass their group's `deployment` to `lib/table`.

For a global family, set `layout = "global"` and use `var.deployment.global`. Its storage table is `<name>` with one Keeper path across the participating nodes; it has no Distributed reader. A global family without Kafka creates only storage. Set `storage.replicated = false` for a plain MergeTree reference table. With Kafka, the library also creates its ingestion objects and a writable table routing to one shard of the storage cluster. Replica names must be unique across the participating nodes.

New replication paths use the actual database name, so test databases are isolated without a suffix. Deployment can set a complete `keeper_path` and `replica_name`; `names` can preserve historical object names. Do not change existing Keeper paths as part of a refactor. Before adopting an existing custom database whose path previously used `posthog` plus a suffix, supply that exact complete path.
Placement and per-object overrides stay in the calling root. Pass a group's deployment directly to each family; the library selects only that family's overrides.

All existing groups live in the catalogue. Each group has one `main.tf` containing its inputs, columns, families and custom objects. `catalog/main.tf` contains their callers. Shared column lists are declared once and reused. Three legacy Kafka pipelines keep their low-level declarations because their input schemas carry codecs.

Keep unusual views, dictionaries and extra ingestion pipelines in explicit modules built from `lib/table`, `lib/materialized_view`, `lib/view` and `lib/dictionary`. A family does not have to fit the standard five-object pattern.

Run the library check with a local ClickHouse and Keeper:

```bash
bin/clickhouse-schema test-family
```

The check creates and removes its own scratch database, checks storage-only physical attributes and computed-column routing, and requires an empty second plan.

## Objects and placement

Every object has one name and one definition in the catalogue. A group is only a directory that keeps related objects
and their shared column lists together: `catalog/events`, for example, has the sharded data table, the Distributed
tables that read from it and write to it, the Kafka table and the materialized view that fills it.

A root says which objects go on a node by listing their names in `objects`. The catalogue creates exactly those, and
`overrides` changes single objects by name. `lib/table/main.tf` lists the override keys for tables; views,
materialized views and dictionaries accept the arguments of their `lib` module as keys.

A materialized view must be on the same node as the tables it reads from and writes to. `lib/materialized_view`
checks this at plan time and names the missing table.

`test = true` is not a placement: it switches the definitions the test suite expects, such as the `log_entries` test
table in place of its reader.

## What this repository owns

This repository owns the catalogue and one root: `local/`, which puts its objects on a single server.
That root is what local development, tests, CI and self-hosted installs use. `local/objects.tf` lists its objects,
with separate lists for Kafka ingestion and for the test suite.

Which objects are on which nodes in PostHog Cloud is decided in the infrastructure repository, one root per cluster.
Groups whose objects only exist in Cloud (`query_log_archive_v3`, `ops_metrics`, `events_json_buffer` and the other
groups declared from production) are in the catalogue too; `local/` does not list their objects.

## Changing the schema

1. Edit the module of the group. Column lists that several objects use are in its `main.tf`, so a new column usually goes in one place.
2. Write expressions the way ClickHouse prints them in `SHOW CREATE TABLE`. The provider compares your text with what the server reports and ignores only whitespace, so `x::Date` instead of `CAST(x, 'Date')` shows up as a change on every plan. The exception is text inside a quoted string, such as the `QUERY` of a dictionary source: ClickHouse stores that as written.
3. A standard family goes in `catalog/` and uses `lib/table_family`. An unusual object goes in its catalogue group. A new custom group is a directory under `catalog/` and a caller in `catalog/main.tf`. Add every new object's name to a list in `local/objects.tf`.
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

`bin/migrate --scope=clickhouse` and `python manage.py migrate_clickhouse` create the database, call the script and load the reference data.
The test suite builds its databases the same way, with `CLICKHOUSE_SCHEMA_KAFKA=false` and `CLICKHOUSE_SCHEMA_TEST=true`. Each regular test process recreates its database first and supplies a complete Keeper path with a unique run ID and the `{table}` macro. This avoids reconciling fixture definitions and reusing paths still owned by asynchronous table drops. AI evaluations retain their database between runs.
It records that initial schema once per test process and restores it between packages and after destructive fixtures.
In tests, the `logs` and `logs_distributed` entry points both route to `logs32` and use its columns, as existing fixtures expect. Test objects include counter metrics and start without the AI columns that runtime materialization adds.
Schema refactors must preserve product test inputs and assertions. SQL factories still called by isolated test fixtures remain available; they do not apply deployment migrations.

No state has been deployed for this system, so it has no state-address migration blocks. Bootstrap imports in cloud roots adopt existing objects.

No state is committed.
The script keeps the OpenTofu state of each target under `~/.cache/posthog-clickhouse-schema`, and the provider adopts objects that already exist, so a lost state costs nothing.

To work on the provider itself, set `CLICKHOUSE_SCHEMA_PROVIDER_SRC` to a checkout of it and the script builds the provider from there.
