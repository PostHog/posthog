# Landed-data invariant queries

Parameterized HogQL to run against synced tables after a live sync (Tier 2), and fleet-side queries for the post-merge watch.
Several are the exact acceptance criteria shipped inside the fix PRs they reference — when one fails, the defect catalog entry tells you what class of bug you're looking at.

Substitute `{table}` with the warehouse table name (as shown in the SQL editor), `{pk}` with the primary key (use `tuple(a, b)` for composites).

## 0. Effective sync type and key (run before anything below)

Nothing under here means anything until you know how the table is written and what it merges on.

```sql
SELECT name, sync_type, status, last_synced_at
FROM system.source_schemas
WHERE should_sync AND deleted = 0
```

Only `incremental` tables merge, so only they are expected to satisfy query 1; a `full_refresh` or append table failing it is the design, not a defect.

`system.source_schemas` does not carry the key. Read that from `primary_key_columns` on the schema API (`GET .../external_data_schemas/`) or the table's sync-method editor, and compare it against the key the source declares in `settings.py`.
A difference is not a bug by itself — a persisted key always wins over a fresh declaration (SKILL.md, Tier 0 step 4) — but it decides which key query 1 runs with, and whether a key fix in the diff reaches this table at all.

## 1. Primary-key integrity (every merge table, every sync)

```sql
SELECT count() AS rows, uniqExact({pk}) AS distinct_keys
FROM {table}
```

`rows` must equal `distinct_keys`.
A gap means the merge predicate isn't matching — most often a partition key that is not a pure function of the key (#82959), a positional key on regenerated files (#82099), or a fan-out child key missing its parent id.
The gap can be a tiny fraction of the table and still be the bug; do not eyeball it away.

## 2. Duplicate hotspots (when query 1 fails)

```sql
SELECT {pk} AS key, count() AS copies
FROM {table}
GROUP BY key
HAVING copies > 1
ORDER BY copies DESC
LIMIT 20
```

Pull a few offenders and diff their rows: identical rows point at partition drift; differing values point at restatements landing as new rows (#82099, #82974).

## 3. Zero-row completion (every enabled table)

An implemented table that lands nothing for anyone, while reporting success, is worse than no table (#82961, #78127).
Locally after a smoke sync, list the armed schemas and their claimed state:

```sql
SELECT name, status, last_synced_at
FROM system.source_schemas
WHERE should_sync AND deleted = 0
```

(HogQL footguns, inherited from the data-warehouse scout: `should_sync` is a `Boolean` — use it bare; `deleted` is an `Integer` — compare `= 0`.)
Every enabled schema must have a queryable table with `count() > 0`, or the sync must have raised.
There is no acceptable third state.

## 4. Month-gap scan (incremental and windowed tables)

```sql
SELECT toStartOfMonth({cursor_field}) AS month, count() AS rows
FROM {table}
GROUP BY month
ORDER BY month
```

Look for holes and cliffs.
A hard cliff at a fixed distance from today is the signature of a horizon clamp or a walk that can't keep up and never catches up (#82115).
Compare the earliest month against the configured `start_date` and the vendor's retention.

## 5. Parent/child coverage join (fan-out tables)

The per-month invariant #82115 shipped as its acceptance criterion, generalized:

```sql
SELECT
    toStartOfMonth(p.{parent_ts}) AS month,
    uniqExact(p.{parent_pk}) AS parents,
    uniqExact(c.{child_parent_fk}) AS parents_with_children
FROM {parent_table} AS p
LEFT JOIN {child_table} AS c ON c.{child_parent_fk} = p.{parent_pk}
GROUP BY month
ORDER BY month
```

For a child that should exist for (nearly) every parent, coverage below ~99% in any month means the child walk is dropping windows while reporting success.

## 6. Restatement sanity (report-file sources)

For sources that retain every vintage of a restated report (#82974):

```sql
SELECT sum({measure}) AS naive_sum
FROM {table}
```

versus

```sql
SELECT sum(latest) AS deduped_sum
FROM (
    SELECT {grain_columns}, argMax({measure}, {vintage_column}) AS latest
    FROM {table}
    GROUP BY {grain_columns}
)
```

A large ratio means vintages are retained — which is fine **only if** the table/column descriptions carry the dedup recipe so readers (human and AI) apply it.
Verify the deduped sum against a known-true number from the vendor's UI.

## 7. Second-sync idempotence

Snapshot query 1 before and after an immediate re-sync:

- merge tables: `distinct_keys` stable, `rows == distinct_keys` still
- full refresh: `rows` unchanged (modulo genuine upstream changes)
- append tables: growth equals genuinely new rows only — boundary re-reads must not re-land (#80183)

## Fleet-side queries (post-merge watch)

Self-driving first: the data-warehouse Signals scout already sweeps `system.source_schemas` on every enabled project and files Inbox reports for armed-but-failed schemas, silent staleness, dead webhook channels, and row-volume cliffs.
Leave it a note naming the changed source type and deploy date (SKILL.md, Tier 2), then use the replica queries below for the cross-fleet view the per-project scout cannot give you.

Run these on the internal dogfood replicas (setup and caveats in `/auditing-warehouse-source-coverage` step 2 — including: confirm column names against `system.information_schema.columns` first, the replica schema drifts).
Results are internal operational data: use them to decide, never commit them anywhere public.

Schemas of the changed source type in a bad or suspicious state, both regions:

```sql
SELECT
    status,
    count() AS schemas,
    uniqExact(team_id) AS teams,
    countIf(table_id IS NULL) AS no_table,
    countIf(last_synced_at IS NULL) AS never_synced
FROM (
    SELECT s.status AS status, s.team_id AS team_id, s.table_id AS table_id, s.last_synced_at AS last_synced_at
    FROM postgres_posthog_externaldataschema AS s
    JOIN postgres_posthog_externaldatasource AS src ON src.id = s.source_id
    WHERE src.source_type = '{SourceType}' AND s.should_sync = true
    UNION ALL
    SELECT s.status, s.team_id, s.table_id, s.last_synced_at
    FROM eu_postgres_posthog_externaldataschema AS s
    JOIN eu_postgres_posthog_externaldatasource AS src ON src.id = s.source_id
    WHERE src.source_type = '{SourceType}' AND s.should_sync = true
)
GROUP BY status
ORDER BY schemas DESC
```

`no_table` and `never_synced` are in the projection because grouping on status alone hides the failure this tier exists for: a schema reporting `Completed` with nothing behind it counts as healthy in a `Completed` row.

Watch for:

- any `Completed` row with `no_table` or `never_synced` above zero — the silent-success signature (#82961); pull those schemas individually rather than reading the group total
- schemas in a failure/paused status that appeared after the deploy — pull their `latest_error` strings; a new error string shared across many teams is the fleet-wide signature that separated a bad default from one broken account (#78035)
- for loud regressions in one customer's sync rather than the fleet, hand off to `/triaging-warehouse-sync-tickets`
