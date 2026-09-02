# HogQL to Trino compilation

The Trino backend compiles a resolved HogQL query into SQL and bound values. It does not connect to Trino or enable HogQL on an existing Query Editor connection.

## Release boundary

Call `prepare_and_print_ast(node, context, "trino")` explicitly to use the backend. Normal query routing and the raw-only Trino adapter remain unchanged. The compiler and lowering modules load only when a caller selects the Trino dialect.

The returned SQL uses named placeholders, with values stored in `context.values`. `convert_pyformat_placeholders` converts these into positional placeholders and values for a Trino client; calling this helper does not execute SQL.

The existing preparation path still owns schema construction, access checks, saved-query expansion, lazy-table resolution, and resolver passes. It then passes the prepared AST and snapshots of bindings, table locators, modifiers, limits, timezone, and week start in a frozen input to the final Trino transpiler. The final transpiler clones the AST and creates a fresh print context without a team, user, or schema database before final lowering, validation, and printing.

This boundary does not add a restricted manifest-backed entry point. Callers still use the Django-backed preparation path described below.

Query Editor capability changes, case-insensitive connection lookup, and parameter submission belong to a separate connection-integration change. They are not prerequisites for compilation.

For supported string, array, and map arguments, `empty(x)` returns true when the value is NULL or has zero length. `notEmpty(x)` requires a non-NULL value with nonzero length. String predicates use an empty-string comparison; arrays and maps use `cardinality`.

## Why some shared integration is necessary

The backend owns its function mappings, structural rewrites, validation, and table rendering. These shared extension points let it reuse the existing compiler without duplicating its semantic pipeline:

| Shared surface                        | Reason                                                                                                        | Effect on other dialects                                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Dialect and runtime-type declarations | Identify Trino throughout resolution and printing.                                                            | Existing dialect membership and behavior stay unchanged.                                                       |
| `HogQLContext.trino_table_locators`   | Carry explicit physical destinations through context copies and semantic expansion.                           | An empty default is unused outside Trino compilation.                                                          |
| `printer/utils.py`                    | Run resolver-dependent Trino lowering before shared expansion, then invoke the detached final transpiler.     | Trino-specific passes and imports require the Trino dialect.                                                   |
| Resolver allowances                   | Accept `TRY_CAST`, positional references, and array slices before the printer sees them.                      | Existing dialect checks retain their previous outcomes.                                                        |
| `BasePrinter` rendering hooks         | Support Trino's limit/offset order, `FETCH FIRST ... WITH TIES`, and `GROUP BY AUTO`.                         | Default hook implementations preserve the existing rendering.                                                  |
| Lazy-table visitor annotations        | The Trino validator visits `LazyTableType`; the common visitor signature must describe that actual node type. | The workload visitor drops an impossible `FunctionCallTable` check; valid lazy-table behavior stays unchanged. |

A standalone printer cannot repair a query rejected earlier by the resolver or introduce relation-shape rewrites after semantic resolution is finished. A separate compiler pipeline could avoid these hooks, but would duplicate the PostHog semantic expansion sequence. The small hooks keep that sequence shared. Overriding complete base-printer methods would likewise duplicate unrelated SELECT and set-operation rendering.

Trino table rendering stays in Trino-specific modules. Neither the built-in numbers table nor the shared direct-Trino table class needs a new rendering method.

## Explicit compilation from Django

After deployment, Django shell can call the same compilation API. Construct the context with the intended team, user, effective modifiers, and `Database.create_for(...)`, then supply explicit Trino locators. No new HTTP endpoint or scheduled job is required.

For managed DuckLake data, call `compile_hogql_to_trino_sql(...)` through the managed-warehouse client facade. This explicit entry point reads the organization's ready Trino catalog from the control plane and combines it with the project's authoritative team row. It maps:

- `events` and `persons` to the project's provisioned tables in the `posthog` schema;
- materialized saved queries to their `posthog_data_modeling_team_<team_id>` DuckLake copies;
- copied warehouse sources to their provisioned data-import schema and table names.

The compiler returns Trino SQL and parameter values by default. Pass `include_hogql=True` to include a normalized HogQL diagnostic; this optional rendering reuses the compilation database.

The control-plane read accepts both `trino_catalog_name` and the earlier `catalog` field during a rolling deployment. A disabled or non-ready Trino target, an organization mismatch, a missing team row, or an unmapped relation fails compilation before SQL submission. The helper only compiles; deploying it does not change query routing or execute Trino SQL.

Trino compilation currently requires `personsOnEventsMode=person_id_override_properties_on_events`. The compiler rejects unset, disabled, V1, and joined modes before semantic lowering so it cannot silently apply V2 person attribution to a query that requested different behavior.

Trino compilation fails when the caller has any effective property-level access restrictions. This applies to the entire query, including queries that do not reference a restricted property directly. The compiler must not return SQL until Trino supports equivalent masking for explicit property reads, whole property blobs, and wildcard projections.

The provisioned persons relation stores one row per distinct ID and can retain person snapshots from more than one export partition. Trino lowering groups direct `persons` reads by person ID and selects values from the latest person version. For V2 event queries, it reads person properties from the exported event row and resolves `person_id` through the latest exported distinct-ID mapping, falling back to the event's physical `person_id`. Managed warehouse persons exports do not include `last_seen_at`, so the compiler rejects that field instead of emitting SQL for a missing column. The DuckLake export contract, rather than the SQL printer, defines deletion behavior.

Source metadata describes what HogQL means. Target mappings describe where the corresponding Trino data exists. Missing mappings and unsupported constructs fail compilation; the compiler must not invent physical relations or assume a ClickHouse materialized view exists in Trino.

`test_trino_semantics.py` exercises action expansion, cohort expansion, V2 person attribution, and unsupported-mode rejection through the compilation API without using the execution adapter. A batch export script is a separate operational tool, not part of this release.

## Validation

Run the Trino printer, semantic expansion, and parameter-helper tests. Run the existing printer/resolver and direct-adapter tests to check shared behavior, and the startup-import guards to check initialization. Do not regenerate existing dialect snapshots simply to make a regression pass.

Compilation success is not proof of target schema compatibility or equivalent results. Validate printed SQL separately against the intended Trino schema and compare results only where the source and target data are comparable.
