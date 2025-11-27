# DuckLake Data Modeling Verification

This document summarizes the automated checks executed after every DuckLake data modeling copy. The row-count verification queries defined in `data_modeling.yaml` are fully configurable, while the remaining structural checks are enforced in Python using metadata derived from the saved-query schema. Together they provide guardrails against schema drift or data loss.

## How verification works

1. `prepare_data_modeling_ducklake_metadata_activity` enriches each model with metadata derived from the `DataWarehouseSavedQuery.columns` definition:
   - `partition_column`: first Date/DateTime column (used for partition comparisons)
   - `key_columns`: inferred IDs (`person_id`, `distinct_id`, etc.)
   - `non_nullable_columns`: columns that are not declared as `Nullable(...)`
2. `verify_ducklake_copy_activity` first runs the SQL queries declared in `data_modeling.yaml` (currently the row-count delta) and then runs the built-in checks below. Any failure stops the workflow.

## Built-in checks

| Check | Description |
| --- | --- |
| `model.schema_hash` | Reads the Delta source schema via DuckDB, reads the DuckLake table schema, hashes both, and fails if hashes differ. Prevents silent schema drift. |
| `model.partition_counts` | When a partition column is available, compares daily row counts between the source Delta table and DuckLake. Any partition mismatch fails verification. |
| `model.key_cardinality.<column>` | For each inferred key column, compares `COUNT(DISTINCT column)` between Delta and DuckLake to catch dropped/duplicate identifiers. |
| `model.null_ratio.<column>` | Ensures DuckLake null counts for columns marked non-nullable match the Delta source so we only fail when DuckLake drifts. |
| `row_count_delta_vs_ducklake` | Defined in `data_modeling.yaml`: compares total row counts using parameterized SQL. |

## Customizing checks

- Add new parameterized verifications by editing `posthog/ducklake/verification/data_modeling.yaml`. These queries run before the built-in checks and can leverage the same metadata via `{ducklake_table}` formatting and parameters.
- Built-in checks (schema hash, partition counts, key-cardinality, null ratios) are intentionally hardcoded and derive their metadata directly from each saved query. To change their behavior you currently need code changes (for example, adjusting the partition-column detector). Future enhancements may expose limited toggles in YAML, but today YAML only controls the additional SQL checks.

## Future enhancements

- Support per-model tolerances / opt-outs via the YAML matrix.
- Persist verification artifacts (e.g., schema diffs, mismatching partition rows) for auditing.
- Emit verification latency/freshness metrics to Temporal dashboards.
