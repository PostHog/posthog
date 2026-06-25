# OPS HCL → migration codegen

Turns a declarative-HCL change into a ClickHouse migration the existing
`infi.clickhouse_orm` runner executes. The HCL stays the source of truth for
*what* the schema is; this generator produces the `run_sql_with_exceptions(...)`
operations for *applying* it.

## How it works

```
edit OPS HCL ──▶ ops/diff.sh (hclexp diff -sql, committed → working)
            ──▶ gen_migration.py: map each DDL statement to its targeting
            ──▶ operations = [run_sql_with_exceptions(...), ...]
```

Two inputs, two responsibilities:

- **`hclexp diff`** gives the DDL (`ALTER TABLE … ADD COLUMN …`, etc.) — derived
  from the HCL, so it's always correct for the schema.
- **`topology.py`** gives `node_roles` per object. This is an explicit, reviewed
  map because `node_roles` is **not** mechanically derivable: the dump
  `hostClusterRole` vocabulary (`ingestion`, `batch_exports`, `sessionsv3`, …)
  doesn't match the `NodeRole` enum, and migrations deliberately target a curated
  subset. `sharded` and `is_alter_on_replicated_table` are derived from the engine
  kind recorded in the map.

The result: one HCL change can emit several operations with **different** roles —
e.g. an OPS replicated data table (`node_roles=[OPS]`,
`is_alter_on_replicated_table=True`) plus its distributed read table everywhere
(`node_roles=ALL_ROLES`, both flags `False`).

## Usage

```bash
# from the repo root; HCLEXP_BIN points at a built hclexp (or rely on the
# bin/hclexp container fallback)
HCLEXP_BIN=../python-clickhouse-schema/hclexp \
  python posthog/clickhouse/hcl/ops/codegen/gen_migration.py --name add_foo_column

#   --ref <git-ref>   diff the working tree against this ref (default HEAD)
#   --out <path|->    write here, or stdout (default)
```

Then: review the output, save it as the next `posthog/clickhouse/migrations/NNNN_<name>.py`,
and bump `max_migration.txt`.

## Behaviors / guardrails

- **Unknown object → hard error.** If a changed object isn't in `topology.py`,
  generation fails — you must add it (a conscious `node_roles` choice) first.
- **UNSAFE changes are flagged.** Storage-class switches / recreations that
  `hclexp` marks `-- UNSAFE` get a `# UNSAFE (review/recreate by hand)` comment;
  these are never silently emitted as a plain ALTER.
- Statements are deduped across env stacks. Per-env DDL differences (e.g.
  `sharded_tophog` zoo_path) still need `settings.CLOUD_DEPLOYMENT` gating by hand —
  the generator does not yet emit those branches.
- DDL keeps the explicit `posthog.` database qualifier as `hclexp` emits it.

## Keeping topology.py current

Seeded by introspecting `../clickhouse-schema` (which roles host each object) and
reconciled against the existing OPS migrations (`0273`/`0274`). When you add or
move an OPS object, add/adjust its entry: `(node_roles, replicated, sharded)`.
