# Data warehouse presentation layer

## The presentation layer stays source-agnostic

The source/schema views here (`views/external_data_source.py`, `views/external_data_schema.py`)
must not branch on a concrete source type. No:

```python
if source_type == ExternalDataSourceType.POSTGRES: ...
elif source.is_direct_snowflake: ...
```

Every such branch splits "how source X behaves" between the source class and the API
layer, and grows the views without bound as new sources land. The API asks _what a
source supports_ and delegates the _how_.

### Where the behaviour goes

Pick the mechanism by the kind of concern:

1. **Source-domain behaviour** (how to talk to the upstream system, whether it supports a
   feature) → the source class under
   `products/warehouse_sources/backend/temporal/data_imports/sources`:
   - **A boolean/value the API reads** → a flag on `_BaseSource` with a safe default
     (like `supports_column_selection`, `connection_host_fields`, `has_managed_hogql_schema`).
     Branch on the flag.
   - **Methods only some sources have** (CDC, xmin, webhooks, custom manifests) → a capability
     mixin the source opts into; the API dispatches with `isinstance(source, <Capability>)`.

2. **Direct-query engine behaviour** (how a SQL engine resolves a table location, builds and
   reprojects its `DataWarehouseTable`, maps columns) → an **engine-keyed adapter**, dispatched
   on `source.direct_engine` (via `DIRECT_ENGINE_BY_SOURCE_TYPE` / `is_direct_capable`), never on
   `source_type`. The engine, not the source type, is the axis of variation, and the same engine
   can back more than one source. Query-side engine behaviour already lives in the
   `posthog/hogql/direct_sql/` adapter registry; the warehouse-side materialization
   (`get_*_source_location`, `upsert_direct_*_table`, `reproject_direct_*_table`,
   `*_columns_to_dwh_columns`) belongs behind the matching `data_warehouse` engine registry.

Whatever the mechanism, source-domain semantics live on the source and warehouse-domain work
(`DataWarehouseTable` rows, managed viewsets, hog functions) stays here, keyed off what the
source / adapter returns. Source capabilities never import `data_warehouse` types.

### Enforcement

`.github/scripts/check-dwh-source-agnostic.py` is a shrink-only CI guard (run in
`ci-backend.yml`). It counts every `ExternalDataSourceType.<NAME>` / `SourceType.<NAME>` /
`is_direct_<engine>` reference in this directory against a baseline
(`source_agnostic_baseline.txt`). A new reference fails CI; migrating a family lets you shrink
the baseline:

```bash
python .github/scripts/check-dwh-source-agnostic.py --regenerate-baseline
```

The baseline only shrinks. When it hits zero, delete the guard.

See `implementing-warehouse-sources` for how to add behaviour to a source.
