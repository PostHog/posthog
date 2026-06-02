# HogQL type-system observability

This module (`observability.py`) measures how well the HogQL type system infers types,
and the shape of the SQL that inference produces.
It exists so we can improve type inference deliberately:
establish a baseline, validate that a change actually raises coverage, and let the data point at where to focus next.

Why it matters: the inferred type of an expression decides the SQL we generate.
A precise type yields clean, fast SQL;
an unknown or partial type forces defensive fallbacks (extra casts, null wrappers, JSON extraction instead of materialized columns) that are slower and a frequent source of subtle correctness bugs.
So "how often do we know the type" is a direct proxy for query quality.

## How it works

1. `prepare_and_print_ast` (in `printer/utils.py`) creates a per-pass `HogQLTypeObservability` accumulator at the start of every prepare+typecheck pass.
2. As the AST is resolved and transformed, instrumented call sites push observations into the accumulator:
   - `resolver.py` calls `record_function_call` for every function call (return-type precision + whether signature metadata existed).
   - `transforms/property_types.py` calls `record_property_definition_lookup` for event/person/group property lookups.
   - the printer records `inference_exception` if the pass throws.
3. After the AST is prepared, two `TraversingVisitor`s walk it:
   `TypeCoverageCollector` tallies every expression by type precision, and `SQLShapeCollector` tallies defensive-SQL patterns.
4. `emit_hogql_type_observability` flushes the accumulator into Prometheus counters/histogram and the accumulator is discarded.

Everything is gated by a single module constant, `TYPE_OBSERVABILITY_SAMPLE_RATE` (default `0.01` = 1% of passes; `0` disables).
The collectors traverse the whole prepared AST, so sampling bounds that cost — at production volume full sampling would be too expensive to leave on.
Bump it locally (e.g. `1.0`) when actively working on inference.

## Cardinality and labels

Labels are deliberately **low-cardinality** — no raw query text, no specific function or property names, no PII.
This keeps Prometheus healthy and avoids leaking customer query content into metrics.
The cost is that metrics get you to a _category_ (e.g. "tuple functions lack signatures"), and you then drop to code or a local repro to find the exact culprit.
This is observability, not tracing.

Every metric carries these base labels:

| Label     | Meaning                                                                                | Example values                             |
| --------- | -------------------------------------------------------------------------------------- | ------------------------------------------ |
| `engine`  | Which type-inference engine produced the pass                                          | `current`                                  |
| `dialect` | Target SQL dialect being printed                                                       | `clickhouse`, `hogql`                      |
| `source`  | The surface/call site that triggered the query (`observability_source` on the context) | `sql_editor`, `insights`, `api`, `unknown` |

`source` is `unknown` until call sites set `context.observability_source`;
wiring those is a planned follow-up so coverage can be sliced per surface.
`engine` is the axis intended for A/B comparison: a future reworked engine should emit under a distinct value so old and new can be compared on identical traffic.

## Metrics reference

All counters below are in addition to the three base labels.
"Status" marks whether a metric is currently populated or reserved (declared and emitted, but no call site increments it yet).

### Pass-level

| Metric                             | Type      | Extra labels                             | What it measures                            | Why / how to use                                                                                                                                                                                    |
| ---------------------------------- | --------- | ---------------------------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hogql_typecheck_total`            | counter   | `result` (`success` / `error` / `empty`) | One per sampled prepare+typecheck pass      | Activity denominator and reliability signal. Error ratio: `sum(rate(...{result="error"}[$__rate_interval])) / sum(rate(...[$__rate_interval]))`. A sustained climb means the type pass is throwing. |
| `hogql_typecheck_duration_seconds` | histogram | —                                        | Wall-clock of a full prepare+typecheck pass | Latency of inference itself; guards against a change making typing slower. `histogram_quantile(0.95, sum by (le) (rate(..._bucket[$__rate_interval])))`.                                            |

### Expression coverage — the north-star

| Metric                            | Type    | Extra labels                                    | What it measures                                        | Why / how to use                                                                                                                                                                       |
| --------------------------------- | ------- | ----------------------------------------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hogql_expression_observed_total` | counter | —                                               | Total `Expr` AST nodes visited during coverage sampling | Denominator for coverage.                                                                                                                                                              |
| `hogql_expression_typed_total`    | counter | `precision` (`precise` / `partial` / `unknown`) | Every expression bucketed by how well it was typed      | **The headline coverage metric.** Track the _share_ that is `precise` (drive up) vs `unknown` (drive down): `sum by (precision) (rate(...[$__rate_interval]))` as a 100%-stacked view. |

Precision is defined in `classify_expr_type` / `classify_constant_type`:

- **precise** — resolved to a concrete scalar `ConstantType` (e.g. `StringType`, `IntegerType`), including fully-typed tuples/arrays.
- **partial** — a real `Type` that is not a scalar constant: field/table/column references, subquery outputs. Structure is known, the value type is not. A large `partial` bucket is normal and not inherently bad.
- **unknown** — `None` or `UnknownType`: inference gave up.

### Why inference fails — the backlog

| Metric                     | Type    | Extra labels | What it measures                                    | Why / how to use                                                                |
| -------------------------- | ------- | ------------ | --------------------------------------------------- | ------------------------------------------------------------------------------- |
| `hogql_type_unknown_total` | counter | `reason`     | Each time inference gives up, attributed to a cause | This panel **is the prioritized backlog** — the biggest bar is the biggest win. |

`reason` is drawn from a fixed vocabulary (`_UNKNOWN_REASONS`).
Currently emitted:

| Reason                       | Emitted when                                                                                    |
| ---------------------------- | ----------------------------------------------------------------------------------------------- |
| `missing_function_signature` | a function call returned unknown and the function had no signature metadata                     |
| `signature_mismatch`         | a function call returned unknown despite having signatures (no signature matched the arg types) |
| `unknown_property_metadata`  | a property lookup had no type metadata                                                          |
| `inference_exception`        | the prepare+typecheck pass raised                                                               |

Reserved (in the vocabulary, not yet wired — populate as inference is extended):
`unsupported_ast_node`, `property_metadata_conflict`, `unknown_database_field_type`, `set_query_type_conflict`, `lambda_type_unbound`, `dialect_gap`, `transform_invalidated_type`.

### Functions — the largest source of unknowns

| Metric                                    | Type    | Extra labels     | What it measures                                                                 | Why / how to use                                                                                                                                                              |
| ----------------------------------------- | ------- | ---------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hogql_function_call_total`               | counter | —                | Function calls observed during resolution                                        | Denominator for function typing.                                                                                                                                              |
| `hogql_function_return_typed_total`       | counter | `precision`      | Function-call return types bucketed by precision                                 | Shows what fraction of function calls come back typed. Typically the biggest `unknown` contributor.                                                                           |
| `hogql_function_signature_miss_total`     | counter | `function_group` | Calls that returned unknown because **no** signature metadata existed            | Ranks which function categories lack signatures. Top group = highest leverage; cross-reference `HOGQL_CLICKHOUSE_FUNCTIONS` to get the exact functions and add `signatures=`. |
| `hogql_function_signature_mismatch_total` | counter | `function_group` | Calls that returned unknown despite signatures being present (args matched none) | A different fix from a miss: the signature exists but is wrong/incomplete. Usually needs a repro to see the real arg types.                                                   |

`function_group` is a coarse bucket from `classify_function_group` (kept low-cardinality on purpose):
`comparison`, `logical`, `cast`, `datetime`, `string`, `json`, `array`, `tuple`, `map`, `aggregate`, `aggregate_state`, `posthog`, `url`, `math`, `unknown`.

### Properties

| Metric                                    | Type    | Extra labels                                      | What it measures                                                          | Why / how to use                                                                                    | Status                                                                 |
| ----------------------------------------- | ------- | ------------------------------------------------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `hogql_property_typing_total`             | counter | `result` (`{event,person,group}_{known,unknown}`) | Property-definition lookups by source and whether type metadata was found | `*_unknown` rising means event/person/group property types are missing at type time.                | active                                                                 |
| `hogql_materialized_property_usage_total` | counter | `result`                                          | Intended: materialized-column access vs JSON extraction                   | Will show how often property access hits a materialized column (fast) vs falls back to JSON (slow). | **reserved** — declared and emitted but no call site increments it yet |

### Generated-SQL shape — the downstream cost

| Metric                  | Type    | Extra labels | What it measures                                                              | Why / how to use                                                                                                                                |
| ----------------------- | ------- | ------------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `hogql_sql_shape_total` | counter | `shape`      | Defensive constructs found in the printed SQL, tallied by `SQLShapeCollector` | This is the **cost** of imprecise types made visible. High counts mean inference is forcing defensive SQL; they should fall as precision rises. |

`shape` values: `datetime_cast`, `numeric_cast`, `string_cast`, `boolean_cast`, `nullable_comparison_wrapper`, `assume_not_null`, `json_extract`, `json_extract_raw`, `property_conversion_wrapper`.

## Drilling from a metric to a fix

1. In Grafana, narrow as far as the labels allow: `hogql_type_unknown_total` by `reason` → if function-driven, `hogql_function_signature_miss_total` by `function_group` → slice by `dialect` / `source`.
2. The labels stop at the category. To get the specific function/property, go to code: e.g. a `missing_function_signature` + `tuple` finding maps directly to the tuple entries in `posthog/hogql/functions/` that lack `signatures=`.
3. If you need per-query detail (e.g. the actual mismatching arg types), do **not** add high-cardinality labels — sample the raw query/function name to logs or error-tracking at the `record_*` site instead, mirroring the parser's shadow-divergence path.

## Viewing locally

PostHog exposes Prometheus metrics at `/_metrics` (port 8000) when `DEBUG=1`.
Point a Prometheus instance at it and add that Prometheus as a Grafana datasource;
the metrics above are then queryable. Remember to raise `TYPE_OBSERVABILITY_SAMPLE_RATE` locally or the 1% default makes the board fill slowly.

## Extending it

- **Add a new gap reason:** add the string to `_UNKNOWN_REASONS`, then call `stats.record_unknown("your_reason")` at the inference site. `_bounded` keeps anything off-list as `unknown`.
- **Wire a reserved metric:** increment the corresponding accumulator field at the right site (e.g. populate `materialized_property_usage` where property access resolves to a materialized column vs JSON).
- **Add a metric:** declare a module-level `Counter`/`Histogram` (low-cardinality labels), accumulate during the pass, and emit it in `emit_hogql_type_observability`. Keep labels bounded.
