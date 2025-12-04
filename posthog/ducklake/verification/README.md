# DuckLake Data Modeling Verification

This document summarizes the automated checks executed after every DuckLake data modeling copy. Each copy finishes by running `verify_ducklake_copy_activity` in `posthog/temporal/data_modeling/ducklake_copy_workflow.py`, which issues direct DuckDB comparisons between the Parquet source and the freshly created DuckLake table. The YAML in `data_modeling.yaml` adds configurable SQL checks (for example, a row-count delta), while the workflow code enforces structural comparisons (schema, partitions, key cardinality, null ratios) that are derived from each saved query’s metadata. Together they catch schema drift or data loss before the workflow completes.

## How verification works

1. `prepare_data_modeling_ducklake_metadata_activity` enriches each model with metadata derived from the `DataWarehouseSavedQuery.columns` definition so we know **what** to compare:
   - `partition_column`: primary partition column reported by the Delta table metadata
   - `key_columns`: inferred IDs (`person_id`, `distinct_id`, etc.) for distinct-count checks
   - `non_nullable_columns`: any column that is not declared as `Nullable(...)`
2. `verify_ducklake_copy_activity` (see `posthog/temporal/data_modeling/ducklake_copy_workflow.py`) materializes the DuckLake table, executes the SQL queries from `data_modeling.yaml`, and then issues the built-in comparisons below directly in DuckDB. Any failure stops the workflow.

## Built-in checks

| Check                            | Description                                                                                                                                             |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model.schema_hash`              | Reads the Delta source schema via DuckDB, reads the DuckLake table schema, hashes both, and fails if hashes differ. Prevents silent schema drift.       |
| `model.partition_counts`         | When a partition column is available, compares daily row counts between the source Delta table and DuckLake. Any partition mismatch fails verification. |
| `model.key_cardinality.<column>` | For each inferred key column, compares `COUNT(DISTINCT column)` between Delta and DuckLake to catch dropped/duplicate identifiers.                      |
| `model.null_ratio.<column>`      | Ensures DuckLake null counts for columns marked non-nullable match the Delta source so we only fail when DuckLake drifts.                               |
| `row_count_delta_vs_ducklake`    | Defined in `data_modeling.yaml`: compares total row counts using parameterized SQL.                                                                     |

## Customizing checks

- Add or update parameterized verifications by editing `posthog/ducklake/verification/data_modeling.yaml`. The YAML file feeds into `DuckLakeCopyVerificationQuery` objects (see `posthog/ducklake/verification/config.py`), which are passed unchanged into `verify_ducklake_copy_activity`. The workflow renders the SQL, binds any listed parameters, and records the single numeric value returned by the query.
- Each query may declare both an `expected` value and a `tolerance`. During runtime the workflow compares the observed value to `expected` and considers the query passing when `abs(observed - expected) <= tolerance`. If you omit either field, the runtime defaults to `0.0`, so set a tolerance whenever you expect minor drift.
- Built-in checks (schema hash, partition counts, key-cardinality, null ratios) are intentionally hardcoded in `posthog/temporal/data_modeling/ducklake_copy_workflow.py` and always run after the YAML queries. They rely on metadata detected from each saved query, so changing their behavior still requires Python changes today.

### Per-model configuration

YAML defaults apply to every model, but you can override or extend them without touching Python by adding entries under the `models:` section. Each entry is keyed by the workflow `model_label` and can either inherit the defaults or replace them entirely. Example:

```yaml
defaults:
  queries:
    - name: row_count_delta_vs_ducklake
      sql: ...
      tolerance: 0
models:
  people_daily_summary:
    inherit_defaults: true # still runs the default row-count comparison
    queries:
      - name: row_count_delta_vs_ducklake
        description: Allow a larger gap for this model’s backfill window
        sql: |
          SELECT ABS(
              (SELECT COUNT(*) FROM delta_scan(?))
              -
              (SELECT COUNT(*) FROM {ducklake_table})
          )
        parameters:
          - source_table_uri
        expected: 0
        tolerance: 500
```

In this example the `people_daily_summary` model reuses the default query but sets a per-model tolerance of 500 rows, so transient row-count differences no longer fail verification. You can also set `inherit_defaults: false` to run _only_ the queries you specify.

## Future enhancements

- Expose YAML-level toggles for the built-in comparisons (e.g., disabling partition checks for a single model without editing Python).
- Persist verification artifacts (e.g., schema diffs, mismatching partition rows) for auditing.
- Emit verification latency/freshness metrics to Temporal dashboards.
