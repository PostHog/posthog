# DuckLake `ducklake_add_data_files` partition index bug

## Summary

When registering pre-written parquet files into a DuckLake table whose partition spec applies **multiple transforms to a single source column** (e.g. `year(timestamp)`, `month(timestamp)`, `day(timestamp)`), `ducklake_add_data_files()` writes every `ducklake_file_partition_value` row at the **highest** `partition_key_index` instead of spreading them across the spec's columns. The catalog ends up with the right partition VALUES but at the wrong INDEXES, breaking partition pruning and tier-3 compaction (which raises `DuckLakeCompactor: Files have different hive partition path`).

## Symptom in the catalog

For an events table partitioned by `(year(timestamp), month(timestamp), day(timestamp))` at `partition_key_index` 0/1/2, a registered file at S3 path `.../year=2026/month=06/day=29/...` produces:

```text
data_file_id | partition_key_index | partition_value
xxx          | 2                   | 2026     ← year, wrong slot
xxx          | 2                   | 6        ← month, wrong slot
xxx          | 2                   | 29       ← day, correct slot
```

Expected:

```text
data_file_id | partition_key_index | partition_value
xxx          | 0                   | 2026     ← year
xxx          | 1                   | 6        ← month
xxx          | 2                   | 29       ← day
```

Same shape on a 2-column persons spec (`year(_timestamp), month(_timestamp)`): both values land at `partition_key_index = 1`.

## Detection query

```sql
-- Files where any ducklake_file_partition_value row sits at an obviously-wrong slot
SELECT df.data_file_id, file_partition_value.partition_key_index, file_partition_value.partition_value, df.path
FROM ducklake_data_file df
JOIN ducklake_file_partition_value file_partition_value USING (data_file_id)
WHERE df.table_id = <tid> AND df.end_snapshot IS NULL
  AND (
    (file_partition_value.partition_key_index = 0 AND file_partition_value.partition_value::INT NOT BETWEEN 1900 AND 9999) OR
    (file_partition_value.partition_key_index = 1 AND file_partition_value.partition_value::INT NOT BETWEEN 1 AND 12) OR
    (file_partition_value.partition_key_index = 2 AND file_partition_value.partition_value::INT NOT BETWEEN 1 AND 31)
  )
LIMIT 50;
```

A more direct test: any file whose distinct `partition_key_index` set has size 1 but the spec has >1 partition column.

## Root cause

`src/functions/ducklake_add_data_files.cpp:1233-1240`:

```cpp
unordered_map<idx_t, idx_t> field_partition_key_map;
for (auto &partition_fields : partition_data->fields) {
    field_partition_key_map[partition_fields.field_id.index] = partition_fields.partition_key_index;
}
for (auto &hive_partition : file.hive_partition_values) {
    result.partition_values.push_back(
        {field_partition_key_map[hive_partition.field_index.index], hive_partition.hive_value});
}
```

The map keys on `field_id.index` alone. When the spec has multiple partition fields whose `field_id` points at the SAME source column (year/month/day transforms all derived from `timestamp`), each iteration of the first loop OVERWRITES the prior map entry. The last write wins, which is the spec's last column — by convention the highest `partition_key_index`.

| Iteration | field_id.index | partition_key_index written | Map state for that key |
| --------- | -------------- | --------------------------- | ---------------------- |
| 1 (YEAR)  | timestamp.idx  | 0                           | → 0                    |
| 2 (MONTH) | timestamp.idx  | 1                           | → 1 (overwrites 0)     |
| 3 (DAY)   | timestamp.idx  | 2                           | → 2 (overwrites 1)     |

The second loop then resolves every hive value (all of which carry `field_index = timestamp.idx`) to `2`. Three rows pushed, all with `partition_key_index = 2`.

## Trigger conditions

- Partition spec contains ≥2 fields whose `field_id` is the same source column. The canonical Iceberg time-bucket pattern (year/month/day on a single timestamp column) fits exactly. Any spec with all distinct source columns is unaffected.
- Triggered on the registration path — `ducklake_add_data_files()`. Direct DuckLake INSERTs through the regular write path are unaffected (they don't extract partition values from hive paths).

## Affected branches

Verified present (identical buggy code block, line numbers within ±2):

| Branch                                            | File:line                                             |
| ------------------------------------------------- | ----------------------------------------------------- |
| `origin/main` (PostHog fork)                      | `src/functions/ducklake_add_data_files.cpp:1233-1240` |
| `ducklabs/main` (upstream main)                   | `src/functions/ducklake_add_data_files.cpp:1235-1241` |
| `ducklabs/v1.5-variegata` (latest release branch) | `src/functions/ducklake_add_data_files.cpp:1233-1240` |

No commit on any branch addresses it. No grep hits on `partition_key_index` / `hive_partition` in recent commit messages.

## Fix (source-level)

Either disambiguate the map key, or skip the map and zip in spec order.

### Option A — key the map on `(field_id, transform)`

```cpp
struct FieldTransformKey {
    idx_t field_id_index;
    DuckLakeTransformType transform;
    bool operator==(const FieldTransformKey &o) const {
        return field_id_index == o.field_id_index && transform == o.transform;
    }
};
struct FieldTransformKeyHash {
    size_t operator()(const FieldTransformKey &k) const {
        return std::hash<idx_t>()(k.field_id_index) ^ (std::hash<int>()(static_cast<int>(k.transform)) << 1);
    }
};
unordered_map<FieldTransformKey, idx_t, FieldTransformKeyHash> field_partition_key_map;
for (auto &pf : partition_data->fields) {
    field_partition_key_map[{pf.field_id.index, pf.transform.type}] = pf.partition_key_index;
}
for (auto &hp : file.hive_partition_values) {
    result.partition_values.push_back(
        {field_partition_key_map[{hp.field_index.index, hp.transform}], hp.hive_value});
}
```

(Requires `HivePartition` to carry the transform type, which it already does per the construction at `:1178-1179`.)

### Option B — zip in spec order

```cpp
for (auto &pf : partition_data->fields) {
    for (auto &hp : file.hive_partition_values) {
        if (hp.field_index.index == pf.field_id.index && hp.transform == pf.transform.type) {
            result.partition_values.push_back({pf.partition_key_index, hp.hive_value});
            break;
        }
    }
}
```

O(n²) but n is the partition column count — tiny.

## Workarounds without a source fix

### Best — post-process the catalog after `ducklake_add_data_files()`

The dagster job already knows year/month/day for every file it registered. Immediately after the registration call, run a follow-up SQL block that DELETEs the bogus ducklake_file_partition_value rows and INSERTs the correct ones. Pseudocode for an events backfill batch:

```python
# 1. Existing call — registers files but populates ducklake_file_partition_value rows incorrectly
result = conn.execute("CALL ducklake_add_data_files(?, ?)", [table, file_paths])

# 2. Workaround: rebuild ducklake_file_partition_value rows for the just-registered files
just_added_paths = [...]  # the file paths we just passed in
conn.execute("""
  DELETE FROM ducklake_file_partition_value
  WHERE data_file_id IN (
    SELECT data_file_id FROM ducklake_data_file
    WHERE table_id = ? AND end_snapshot IS NULL AND path = ANY(?)
  )
""", [table_id, just_added_paths])

conn.execute("""
  INSERT INTO ducklake_file_partition_value (data_file_id, table_id, partition_key_index, partition_value)
  SELECT df.data_file_id, ?, 0, (substring(df.path from 'year=([0-9]+)'))::INT::TEXT
  FROM ducklake_data_file df
  WHERE df.table_id = ? AND df.end_snapshot IS NULL AND df.path = ANY(?)
  UNION ALL
  SELECT df.data_file_id, ?, 1, (substring(df.path from 'month=([0-9]+)'))::INT::TEXT
  FROM ducklake_data_file df
  WHERE df.table_id = ? AND df.end_snapshot IS NULL AND df.path = ANY(?)
  UNION ALL
  SELECT df.data_file_id, ?, 2, (substring(df.path from 'day=([0-9]+)'))::INT::TEXT
  FROM ducklake_data_file df
  WHERE df.table_id = ? AND df.end_snapshot IS NULL AND df.path = ANY(?);
""", [table_id, table_id, just_added_paths, table_id, table_id, just_added_paths, table_id, table_id, just_added_paths])
```

Wrap both in a transaction. Pros: minimal code change, easy to remove once the upstream fix lands. Cons: bypasses DuckLake's snapshot-creating write path (you're modifying catalog rows that were just written by an outer DuckLake transaction — verify the snapshot boundary is sane); take the `hashtext('millpond-ducklake-maintenance')::bigint` advisory lock if running concurrently with the maintenance script.

### Worse — write the catalog rows ourselves, skip `ducklake_add_data_files()` entirely

Implement file registration in dagster: write parquet → INSERT into `ducklake_data_file` + `ducklake_file_partition_value` + snapshot/changes rows ourselves with correct indexes. Larger surface to maintain; loses any future DuckLake-side validation.

### Useless — change the partition spec to avoid the trigger

Spec with one column per source field (e.g. add three separate `timestamp_year`, `timestamp_month`, `timestamp_day` columns and use IDENTITY transforms) would avoid the bug, but requires a schema migration and breaks every partition-pruning predicate that references the original column. Not viable here.

### Useless — change S3 path layout

The bug is field-id collision in catalog construction, not hive path parsing. Different paths won't help.

## Open catalog cleanup needed regardless of fix

The existing bad rows aren't repaired by deploying the source fix — they need a one-time catalog rewrite. The cleanup shape is DELETE-then-INSERT per affected file: the original LEFT-JOIN-INSERT pattern is insufficient because existing rows at the wrong index don't trip a "missing index N" guard. Scope: every customer warehouse whose dagster events/persons backfill has ever run, since the buggy registration path is on every code path that calls `ducklake_add_data_files`.

## Status

The dagster workaround is in `posthog/dags/events_backfill_to_duckling.py` (`_fixup_partition_values_for_added_files`) and runs after every `ducklake_add_data_files` call, gated by `DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENABLED` (default on). Source-level fix in DuckLake is deferred — flip the env var off to disable the workaround once the source fix is deployed.
