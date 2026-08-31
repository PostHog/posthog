# HogQL to Trino compilation

The Trino backend compiles a resolved HogQL query into SQL and bound values. The compiler itself does not connect to Trino. A separate adapter integration enables HogQL on Query Editor connections.

## Release boundary

Call `prepare_and_print_ast(node, context, "trino")` explicitly for standalone compilation. Query Editor uses the same backend when a selected direct connection advertises the Trino dialect. The compiler and lowering modules load only when a caller selects the Trino dialect.

The returned SQL uses named placeholders, with values stored in `context.values`. The direct Trino adapter converts them into positional placeholders and submits the ordered values to the Trino client.

The final Trino transpiler accepts a prepared AST plus frozen snapshots of bindings, table locators, modifiers, limits, timezone, and week start. It clones the AST and creates a fresh print context without a team, user, or schema database before final lowering, validation, and printing.

`transpile_hogql_to_trino(...)` is the restricted, manifest-backed front end. Its immutable manifest allowlists logical tables, physical Trino locators, and warehouse column types. `events` and `persons` use fixed built-in schemas. The function resolves and prints with no team, user, Django model, saved query, or lazy database callback, and its tests assert that it executes zero Django queries.

Pure transpilation accepts caller-supplied constant values. It rejects unresolved placeholders, action and cohort references, tables absent from the manifest, non-leaf warehouse column types, and invalid or incomplete manifest entries. Callers needing Django-backed semantics must select the explicit expansion mode described below.

## Query Editor connection integration

The connection integration advertises `TrinoAdapter.dialect = "trino"`. Selecting a Trino connection for a HogQL query uses the shared query executor and Trino compiler. Table and field lookup follow Trino's case-insensitive identifier rules, while printed relations use the connection's catalog, schema, and physical table name.

The adapter converts compiler placeholders into positional driver parameters without interpolating values into SQL. Raw SQL requests without bound values still pass through unchanged. Existing source configuration validation, raw read-only checks, timeouts, and row caps remain in place.

Direct queries cannot join PostHog person tables, so Query Editor normalizes the person-on-events modifier to the compiler's supported mode before Trino preparation. The selected project's modifier remains unchanged.

The integration does not provision catalogs, alter deployments, or make source-only ClickHouse tables available in Trino.

## Managed Trino connections

Call `resolve_managed_warehouse_trino_connection(...)` through the managed-warehouse client facade when a backend job needs a live Trino target. The resolver accepts a target only when the control plane reports the organization as enabled and ready. It reads the catalog plus non-secret host, port, and username from `status.connection`, then combines them with the root password already stored for the managed warehouse. The connection contract redacts that password from its representation.

Call `connect_managed_warehouse_trino(...)` to open the Python Trino client with basic authentication, HTTPS, certificate verification, and a bounded request timeout. The connector has no Duckgres fallback. A disabled target, non-ready state, organization mismatch, malformed endpoint, or missing stored credential fails before opening a socket.

The Django `DuckgresServer` row remains the transitional owner of the existing root secret; it does not become the source of truth for Trino placement. Trino cell assignment, endpoint identity, and catalog naming stay in the control plane. No second Django model or copied control-plane status is required.

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

For managed DuckLake data, call `compile_hogql_to_trino_sql(...)` through the managed-warehouse client facade. This explicit entry point reads the organization's ready Trino catalog from the control plane and combines it with the project's authoritative team row. Pure manifest-backed compilation is the default. It maps `events` and `persons` to the project's provisioned tables in the `posthog` schema, and accepts additional allowlisted warehouse relations through `catalog_manifest`.

Pass `expansion_mode=TrinoExpansionMode.DJANGO` when a query requires actions, cohorts, saved queries, filters, variables, access-controlled warehouse discovery, or other Django-backed semantic expansion. This compatibility mode builds the full database and maps:

- `events` and `persons` to the project's provisioned tables in the `posthog` schema;
- materialized saved queries to their `posthog_data_modeling_team_<team_id>` DuckLake copies;
- copied warehouse sources to their provisioned data-import schema and table names.

The compiler returns Trino SQL and parameter values by default. Pass `include_hogql=True` to include a normalized HogQL diagnostic. Compilation mode is a trusted function argument; serialized `HogQLQuery` input cannot enable Django expansion.

The control-plane read accepts both `trino_catalog_name` and the earlier `catalog` field during a rolling deployment. A disabled or non-ready Trino target, an organization mismatch, a missing team row, or an unmapped relation fails compilation before SQL submission. The helper only compiles; deploying it does not change query routing or execute Trino SQL.

Trino compilation currently requires `personsOnEventsMode=person_id_override_properties_on_events`. Pure mode uses that fixed export contract when the modifier is absent and rejects any explicitly incompatible mode. Django mode resolves the effective team modifier and rejects unset, disabled, V1, and joined modes before semantic lowering.

Trino compilation fails when the caller has any effective property-level access restrictions. This applies to the entire query, including queries that do not reference a restricted property directly. The compiler must not return SQL until Trino supports equivalent masking for explicit property reads, whole property blobs, and wildcard projections.

The provisioned persons relation stores one row per distinct ID and can retain person snapshots from more than one export partition. Trino lowering groups direct `persons` reads by person ID and selects values from the latest person version. For V2 event queries, it reads person properties from the exported event row and resolves `person_id` through the latest exported distinct-ID mapping, falling back to the event's physical `person_id`. Managed warehouse persons exports do not include `last_seen_at`, so the compiler rejects that field instead of emitting SQL for a missing column. The DuckLake export contract, rather than the SQL printer, defines deletion behavior.

Source metadata describes what HogQL means. Target mappings describe where the corresponding Trino data exists. Missing mappings and unsupported constructs fail compilation; the compiler must not invent physical relations or assume a ClickHouse materialized view exists in Trino.

`test_trino_semantics.py` exercises action expansion, cohort expansion, V2 person attribution, and unsupported-mode rejection through the compilation API without using the execution adapter. A batch export script is a separate operational tool, not part of this release.

## Validation

Run the Trino printer, semantic expansion, and parameter-helper tests. Run the existing printer/resolver and direct-adapter tests to check shared behavior, and the startup-import guards to check initialization. Do not regenerate existing dialect snapshots simply to make a regression pass.

Compilation success is not proof of target schema compatibility or equivalent results. Validate printed SQL separately against the intended Trino schema and compare results only where the source and target data are comparable.
