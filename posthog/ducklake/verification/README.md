# DuckLake Copy Verification

This document summarizes the automated checks executed after every DuckLake copy workflow. Both workflows (data modeling and data imports) run verification activities that issue direct DuckDB comparisons between the Delta source and the freshly created DuckLake table. YAML config files add configurable SQL checks (for example, a row-count delta), while the workflow code enforces structural comparisons (schema and partitions). Together they catch schema drift or data loss before the workflow completes.

| Workflow      | Verification Activity                                                                                                  | Config File          |
| ------------- | ---------------------------------------------------------------------------------------------------------------------- | -------------------- |
| Data Modeling | `verify_ducklake_copy_activity` in `posthog/temporal/data_modeling/ducklake_copy_workflow.py`                          | `data_modeling.yaml` |
| Data Imports  | `verify_data_imports_ducklake_copy_activity` in `posthog/temporal/data_imports/ducklake_copy_data_imports_workflow.py` | `data_imports.yaml`  |

## How verification works

Both workflows follow the same pattern:

1. **Metadata preparation** enriches each model with metadata so we know **what** to compare:
   - `partition_column`: primary partition column (from Delta metadata)

2. **Verification activity** executes the SQL queries from the YAML config, then issues the built-in comparisons directly in DuckDB. Any failure stops the workflow.

### Data Modeling specifics

- Metadata derived from `DataWarehouseSavedQuery.columns`
- Partition column detected from Delta table metadata

### Data Imports specifics

- Metadata derived from `ExternalDataSchema` and its associated `DataWarehouseTable.columns`
- Partition column detected from Delta table metadata

## Built-in checks

Both workflows run the same types of checks, but with different prefixes:

| Check Type       | Data Modeling            | Data Imports                    | Description                                                                                                                           |
| ---------------- | ------------------------ | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Schema hash      | `model.schema_hash`      | `data_imports.schema_hash`      | Compares Delta source schema with DuckLake table schema. Fails if they differ. Prevents silent schema drift.                          |
| Partition counts | `model.partition_counts` | `data_imports.partition_counts` | When a partition column is available, compares row counts per partition between source and DuckLake. Any mismatch fails verification. |

Additionally, YAML-defined checks (like `row_count_delta_vs_ducklake`) can be configured per workflow in the respective YAML files.

## Customizing checks

- Add or update parameterized verifications by editing the appropriate YAML file:
  - `posthog/ducklake/verification/data_modeling.yaml` for data modeling workflow
  - `posthog/ducklake/verification/data_imports.yaml` for data imports workflow
- Each YAML file feeds into `DuckLakeCopyVerificationQuery` objects (see `posthog/ducklake/verification/config.py`), which are passed to the verification activity. The workflow renders the SQL, binds any listed parameters, and records the single numeric value returned by the query.
- Each query may declare both an `expected` value and a `tolerance`. During runtime the workflow compares the observed value to `expected` and considers the query passing when `abs(observed - expected) <= tolerance`. If you omit either field, the runtime defaults to `0.0`, so set a tolerance whenever you expect minor drift.
- Built-in checks (schema hash, partition counts) are intentionally hardcoded in the workflow files and always run after the YAML queries. They rely on metadata detected from each model, so changing their behavior still requires Python changes today.

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
