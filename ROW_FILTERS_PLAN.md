# Row Filters for SQL Data Warehouse Sources — Implementation State & Plan

> Temporary tracking file. Delete before the PR is marked ready for review.

## Goal

Schema-level **row filter predicates** for SQL data warehouse sources. A schema carries a list of
`{column, operator, value}` predicates that are ANDed onto the source query's `WHERE` clause on
every sync, so only matching rows are pulled. Mirrors the existing **column selection**
(`enabled_columns`) feature end to end.

Example: on a Postgres source, user picks `col1, col2, col3` for `schema1` and adds a
`col3 > '2026-01-01'` predicate so only matching rows sync.

## Safety design (three rails, enforced backend + frontend)

1. **Column allowlist** — column must exist in the schema's discovered `schema_metadata`.
2. **Operator allowlist** — only `> >= < <= = !=` (accept `==`/`<>` as aliases). The operator
   emitted into SQL is looked up from a frozen map, never passed through from user input.
3. **Typed value** — value validated against the column's type category (classifier covering all
   dialects' type vocabularies, incl. ClickHouse `Nullable(...)` wrappers) and coerced to the
   right Python type.

**SQL injection is impossible by construction:** identifiers go through the existing
`IdentifierQuoter`; values always leave as bound parameters (`sql.Literal`, `%(name)s`,
positional `%s`, or a BigQuery `ScalarQueryParameter`) — never string-interpolated.

## Operators

Allowed: `>`, `>=`, `<`, `<=`, `=`, `!=`. Aliases accepted on input: `==` → `=`, `<>` → `!=`.

## Type categories (classifier)

Categories: `NUMERIC`, `INTEGER`, `STRING`, `BOOLEAN`, `DATE`, `TIMESTAMP`, `UNKNOWN`.
Classifier maps each dialect's native `data_type` string (lowercased, strip `Nullable(...)`,
strip params like `varchar(255)` / `numeric(10,2)`) to a category. Value validation/coercion:
- INTEGER → Python int (reject bool, reject non-integral float/str)
- NUMERIC → int/float/Decimal-parseable string
- STRING → str
- BOOLEAN → bool (accept true/false strings)
- DATE → ISO date string `YYYY-MM-DD`
- TIMESTAMP → ISO datetime string
- UNKNOWN → reject (cannot safely type the value)

## File map (paths relative to repo root `posthog/posthog/`... i.e. the inner package)

Working dir is `/tmp/workspace/repos/posthog/posthog`. The Django package is the nested
`posthog/` dir, so source files live under `posthog/posthog/temporal/...` from cwd, but absolute
paths are clearest. SQL common modules:
`posthog/temporal/data_imports/sources/common/sql/`.

### Backend — core (Step 1)
- `.../common/sql/predicates.py` — NEW. Driver-free: `RowFilter` dataclass/TypedDict,
  `ColumnTypeCategory` enum, `OPERATORS` frozen map, `classify_column_type()`,
  `validate_and_coerce_row_filters()` (validates against schema_metadata columns + types),
  render helpers that return (sql_fragment, params) abstractly.
- `.../common/sql/predicates_psycopg.py` — NEW. psycopg `sql.Composed` clause builder using
  `sql.Literal` for values + `IdentifierQuoter`/`sql.Identifier` for columns. Kept separate so
  the psycopg import stays off the serializer path.
- `.../common/sql/__init__.py` — export driver-free helpers (`RowFilter`, `ColumnTypeCategory`,
  `classify_column_type`, `validate_and_coerce_row_filters`).
- `.../common/sql/query_builder.py` — extend `SelectQueryBuilder.select_all` to accept
  `row_filters` and emit ANDed conditions across all param styles (named/positional/format).

### Backend — model + migration (Step 2)
- `posthog/warehouse/models/external_data_schema.py` (or wherever `ExternalDataSchema` lives) —
  add `row_filters = models.JSONField(null=True, blank=True, default=None)`.
- New migration in the `warehouse_sources` app (mirror the `enabled_columns` migration); update
  `max_migration.txt`.

### Backend — SourceInputs threading (Step 3)
- `.../data_imports/sources/common/typings.py` (`SourceInputs`) — add `row_filters` field with a
  `TYPE_CHECKING` quoted import to avoid a cycle.
- `.../data_imports/import_data_sync.py` — resolve `schema.row_filters` and pass into
  `SourceInputs(...)` (mirror `enabled_columns` resolution).

### Backend — serializer validation (Step 4)
- `posthog/warehouse/api/external_data_schema.py`:
  - custom JSON-backed field class with `@extend_schema_field` for typed generated output.
  - `row_filters` field on `ExternalDataSchemaSerializer` + `Meta.fields`.
  - validate in `update()` after the `enabled_columns` block (uses `schema_metadata`).
- `posthog/warehouse/api/external_data_source.py`:
  - add `row_filters` to the bulk-update schema serializer.
  - validate + persist `row_filters` in the source-creation loop (schema_metadata in scope).

### Backend — 6 SQL sources (Step 5)
Thread `row_filters` from each source's `source_for_pipeline`/`build_pipeline` into `_build_query`
and apply to non-sampling DATA paths only (sampling/count/estimate queries stay unfiltered —
harmless over-estimate, documented):
- `postgres/` — `postgres.py` (`_build_query`, incremental + full branches), `source.py`,
  `partitioned_tables.py` (`build_partition_query`). psycopg `sql.Literal`.
- `redshift/` — `redshift.py`. psycopg `sql.Literal`.
- `mysql/` — via `SelectQueryBuilder` (pyformat/named or positional per driver).
- `mssql/` — pyformat **named** params `%(name)s`.
- `snowflake/` — **positional** `%s` params (ORDER MATTERS — filters appended after existing).
- `bigquery/` — `_get_query` returns `(sql, params)`; filtered plain tables routed through a
  query job with bound `ScalarQueryParameter`s typed from the table schema. Storage-API path
  can't filter, so filtered plain tables MUST use the query-job path.

### Frontend (Step 6)
- `products/data_warehouse/frontend/types.ts` (or wherever `AvailableColumn` lives) — add
  `RowFilter`, `RowFilterOperator` types; add `row_filters?` to the two schema interfaces.
- NEW `rowFilterUtils.ts` — TS classifier mirroring backend (type categories + client validation).
- NEW `RowFilterEditor.tsx` — editor component mirroring `ColumnSelectionPicker` style.
- `ConfigurationTab` (settings) — render a "Row filters" section in the `columns` case alongside
  `ColumnsSection`; include `row_filters` in both `buildSchemaUpdatePayload` PATCH builders.
- New-source wizard — `sourceWizardLogic.tsx` (`setSchemaRowFilters` action + reducer + create
  payload) and `SchemaForm.tsx` (render `RowFilterEditor`; both editors commit-without-closing).

### Tests (Step 7)
- `.../common/sql/tests/test_predicates.py` — classifier, validation, coercion, injection guards.
- `.../common/sql/tests/test_query_builder.py` — `row_filters` across param styles.
- Per-source `_build_query` row-filter tests (postgres incl. partition, redshift, mysql, mssql,
  snowflake, bigquery — esp. positional ordering + bound params).
- Serializer PATCH tests for `row_filters` (DB-backed; run in CI).

### Post-merge / cannot run in sandbox
- `hogli build:openapi` — regenerate `api.schemas.ts` / `api.zod.ts` after serializer change
  (needs dev DB). Frontend compiles via hand-written `~/types` regardless.
- Frontend `format` / `typescript:check` — needs `node_modules`; CI will run.

## Progress

- [x] Step 0: branch + this plan file pushed
- [x] Step 1: core predicates modules + query_builder (predicates.py, predicates_psycopg.py, __init__ exports, SelectQueryBuilder.row_filters) — logic verified
- [ ] Step 1b: tests for predicates + query_builder (deferred to Step 7)
- [x] Step 2: model field + migration (warehouse_sources 0006) — makemigrations --check reports no drift
- [x] Step 3: SourceInputs threading (typings.SourceInputs.row_filters + import_data_sync resolves & re-validates)
- [x] Step 4: serializer + source validation (RowFiltersField + extend_schema_field; ExternalDataSchemaSerializer.update validates; bulk-update serializer field; source-creation loop validates + persists)
- [x] Step 5: 6 SQL sources (MySQL, MSSQL, Snowflake, Redshift, Postgres incl. partitioned/windowed, BigQuery via query job + ScalarQueryParameter) — all import cleanly
- [ ] Step 6: frontend
- [ ] Step 7: tests
- [ ] Step 8: open draft PR; delete this file when ready for review

## Commit/push discipline

Commit + push after EACH step via `git_signed_commit` (creates/updates remote branch) so work
survives environment resets. Branch: `posthog-code/warehouse-row-filters`.
