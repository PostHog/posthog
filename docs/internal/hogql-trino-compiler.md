# HogQL to Trino compilation

The Trino backend compiles a resolved HogQL query into SQL and bound values. The compiler itself does not connect to Trino. A separate adapter integration enables HogQL on Query Editor connections.

## Release boundary

Call `prepare_and_print_ast(node, context, "trino")` explicitly for standalone compilation. Query Editor uses the same backend when a selected direct connection advertises the Trino dialect. The compiler and lowering modules load only when a caller selects the Trino dialect.

The returned SQL uses named placeholders, with values stored in `context.values`. The direct Trino adapter converts them into positional placeholders and submits the ordered values to the Trino client.

The final Trino transpiler accepts a prepared AST plus frozen snapshots of bindings, table locators, modifiers, limits, timezone, and week start. The prepared AST retains resolved table metadata for expanded saved queries. The transpiler clones the AST and creates a fresh print context without a team, user, or schema database before final lowering, validation, and printing.

`transpile_hogql_to_trino(...)` is the restricted, manifest-backed front end. Its immutable manifest allowlists logical tables, physical Trino locators, and warehouse column types. `events` and `persons` use fixed built-in schemas. The function resolves and prints with no team, user, Django model, saved query, or lazy database callback, and its tests assert that it executes zero Django queries.

Use `prepare_trino_catalog(...)` when several queries share one manifest. Preparation validates the manifest and builds its schema database and physical locator map once. Each `PreparedTrinoCatalog.transpile(...)` call creates a new AST, context, modifiers, and bound-value map, so query state does not cross compilation boundaries.

```python
catalog = prepare_trino_catalog(manifest)
first = catalog.transpile("SELECT event FROM events WHERE event = {event}", values={"event": "signup"})
second = catalog.transpile("SELECT count() FROM events")
```

`transpile_hogql_to_trino(...)` remains the one-shot wrapper and prepares a catalog for that call. The manifest contract has no version field, so the compiler does not keep a process-global prepared-catalog cache. Callers must create a new prepared catalog when their immutable manifest snapshot changes.

Pure transpilation accepts caller-supplied constant values. It rejects unresolved placeholders, action and cohort references, tables absent from the manifest, non-leaf warehouse column types, and invalid or incomplete manifest entries. Callers needing Django-backed semantics must select the explicit expansion mode described below.

## Curated warehouse fields in manifests

Physical imports can expose different names and types from the HogQL schema. Supply
`TrinoManifestTable.field_overrides` to retain logical aliases and computed fields in
addition to the physical `columns`. The catalog copies these definitions when it is
prepared; subsequent changes to the caller's definitions do not mutate that catalog.
Core `events` and `persons` manifests still use their fixed schemas and reject overrides.

For example, a logical `customer_id` can be a `StringDatabaseField(name="customer")`,
while `created_at` can be an `ExpressionField` over a raw epoch column. Set
`isolate_scope=True` on computed fields that reference columns of their own table.
Warehouse callers can obtain curated definitions from `resolve_external_table_fields`
using the source resource name and the columns actually present in the import.
Supplying raw column metadata alone omits these semantic mappings.

Trino lowering supports keyed `JSONExtractArrayRaw` as an array of serialized JSON
values, numeric epoch arguments to `toDateTime`, array literal membership, and shared
CTEs across UNION branches. Day-time intervals use native interval arithmetic.
`JSONExtractRaw` also accepts dynamic string keys with JSON-escaped path construction.
Numeric JSON path components use Trino `element_at` so one-based and negative indexes
retain ClickHouse array semantics.

An executable SELECT is not sufficient to establish materialization compatibility:
connectors may reject anonymous nested row fields or untyped NULL output columns.
Callers must validate the intended CREATE TABLE AS operation and its output contract.
A successful build does not establish cross-engine result parity, particularly when
inputs are bounded or the caller applies explicit experimental rewrites.

## Query Editor connection integration

The connection integration advertises `TrinoAdapter.dialect = "trino"`. Selecting a Trino connection for a HogQL query calls the same pure transpiler as managed compilation, handing it the connection-scoped database directly. It does not enable Django semantic expansion. Catalog introspection through `system.information_schema` keeps running on the ClickHouse path. Editor validation prints with the same dialect and rejects the same unsupported features, so a query that validates also compiles.

Table and field lookup follow Trino's case-insensitive identifier rules for discovered tables and columns, including table-qualified column references; explicit aliases keep their written case. Printed relations use the connection's catalog, schema, and physical table name. Tables outside the selected connection are absent from the connection-scoped database. Actions, cohorts, saved queries, content-carrying query filters, variables, and Django-only modifiers receive the pure compiler's existing unsupported-feature errors; a content-free filters object and modifiers carried as explicit nulls pass through.

The adapter converts compiler placeholders into positional parameters and never concatenates values into SQL itself. The Trino client submits them through its prepared-statement emulation, which escapes each value into the `EXECUTE` statement text, so values still appear in Trino's query log and UI. Raw SQL requests without bound values still pass through unchanged. Existing source configuration validation, raw read-only checks, timeouts, and row caps remain in place.

The integration does not provision catalogs, alter deployments, or make source-only ClickHouse tables available in Trino.

## Managed Trino connections

Call `resolve_managed_warehouse_trino_connection(...)` through the managed-warehouse client facade when a backend job needs a live Trino target. The resolver accepts a target only when the control plane reports the organization as enabled and ready. It reads the catalog plus non-secret host, port, and username from `status.connection`, then combines them with the root password already stored for the managed warehouse. The connection contract redacts that password from its representation.

Call `connect_managed_warehouse_trino(...)` to open the Python Trino client with basic authentication, HTTPS, certificate verification, and a bounded request timeout. The connector has no Duckgres fallback. A disabled target, non-ready state, organization mismatch, malformed endpoint, or missing stored credential fails before opening a socket.

The Django `DuckgresServer` row remains the transitional owner of the existing root secret; it does not become the source of truth for Trino placement. Trino cell assignment, endpoint identity, and catalog naming stay in the control plane. No second Django model or copied control-plane status is required.

For supported string, array, and map arguments, `empty(x)` returns true when the value is NULL or has zero length. `notEmpty(x)` requires a non-NULL value with nonzero length. String predicates use an empty-string comparison; arrays and maps use `cardinality`.

Leading CTEs stay in scope across all operands of a set operation. Trino prints them before the parenthesized operands, preserving each operand's ordering and limit. A branch with its own CTEs uses a derived table to keep that scope local.

`IN` and `NOT IN` with array literals print SQL value lists, including the `in(...)` and `notIn(...)` function forms. Empty literals reduce the entire predicate to `FALSE` for membership and `TRUE` for non-membership, including for a NULL left operand, tuple operands, and predicates inside lambdas. Nonempty lists retain SQL NULL comparison behavior. Array expressions outside membership predicates still use Trino's `ARRAY[...]` constructor. These rewrites run in the shared printer for both pure and Django-expanded compilation.

`LIMIT BY` and `QUALIFY` wrappers preserve ordering by projecting unselected sort expressions inside the wrapper and removing those helper columns from the result. The inner query gives projected expressions explicit output aliases, including property accesses, so the outer query can reference them by name. Helper names avoid existing aliases, and matching uses resolved column bindings so joined columns with the same name remain distinct. Expression matching also distinguishes literal types, including `1`, `true`, and `1.0`. `DISTINCT` and `GROUP BY` wrappers still reject unprojected sort expressions. Unprojected aggregate sort expressions are also rejected; callers must select them explicitly. `LIMIT BY` rejects partition or sort expressions containing window functions, including aliases and ordinals resolving to them, because its ranking would otherwise nest window functions.

For ordinary `GROUP BY`, an expression that matches a selected expression uses that output's ordinal. This keeps property paths, date conversions, and other bound expressions identical for Trino's grouping checks. An alias for an integer constant uses the selected expression's position; the constant's value does not become an ordinal. Explicit source ordinals remain unchanged. Alias references inside larger expressions expand to their expressions, not ordinals. Complex grouping modes retain their expressions. These rewrites apply to both pure and Django-expanded compilation.

A top-level `ORDER BY` reference to a selected alias also uses that output's ordinal. This avoids repeating bound parameters from the selected expression and keeps grouped queries valid. Ordering direction and explicit source ordinals remain unchanged; aliases inside larger sort expressions still expand normally.

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

Batch and session callers should use `prepare_hogql_to_trino_compiler(...)` through the same facade. Preparation resolves and validates the ready catalog and project mapping once, then builds the pure manifest catalog. The returned compiler is bound to that organization, project, and catalog and accepts only a `HogQLQuery` per compilation. Additional manifest relations keep their explicitly allowlisted physical locators; Trino authorizes catalog access when the query executes.

```python
compiler = prepare_hogql_to_trino_compiler(team_id, team=team, catalog_manifest=manifest)
queries = [compiler.compile(query) for query in batch]
```

Create a new compiler when the batch needs fresh control-plane placement or team-table mappings. The one-shot `compile_hogql_to_trino_sql(...)` API prepares and compiles in one call. Django expansion stays one-shot because its schema and semantic expansion depend on query-specific team and user state.

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

## Managed warehouse bulk translation

`managed-warehouse.translate-views` is the tracked bulk consumer of the managed-warehouse compiler facade. It calls `compile_hogql_to_trino_sql(...)` with `expansion_mode=TrinoExpansionMode.DJANGO` and `include_hogql=True`, because views reference saved queries and warehouse relations that pure manifest-backed compilation rejects. A `ManagedWarehouseViewTranslationJob` identifies the organization, trigger, Temporal run, aggregate counts, and terminal status. Its team-scoped `ManagedWarehouseViewTranslationResult` rows identify the saved-query snapshot and store either compiled SQL or an error.

Creating a job through Django admin starts the Temporal workflow after the database transaction commits. Provisioning does not create or start these jobs. A job can snapshot every eligible view in the organization or an explicit set of saved-query UUIDs. The workflow validates selected views against the organization and its control-plane-enabled teams, then compiles each represented team independently on the DuckLake task queue.

Compilation is best effort per view. Unsupported HogQL records a failed result and processing continues. A definition changed after the snapshot records a stale result. The workflow stores generated SQL and named values directly from activities so large SQL strings do not cross the Temporal workflow payload boundary. It never executes the SQL, creates Trino relations, or updates `DataWarehouseSavedQuery.query`.

The result admin can retry selected failed or stale rows. A retry creates a new selected-view job linked to the source job, preserving the original job and results as an immutable audit record.

The data modeling shadow path uses these results as an eligibility gate. It requires a ready Trino target and a non-empty compiled result whose source hash matches the saved query's current definition.

## Validation

The Trino printer supports `countDistinctIf`, `replaceOne`, `toFloat64OrNull`,
`arrayCount` with a predicate lambda, `countEqual`, `arraySlice`, `arraySort` with
a single-array key lambda, and `multiSearchAnyCaseInsensitive`. Simple `CASE`
expressions and numeric conditions in `if`/`multiIf` use native Trino conditionals.
Aliases inside expressions are omitted from SQL; projection aliases are retained.
String inputs to `toInt` use `TRY_CAST`, returning NULL for strings that do not
represent an integer. Numeric aggregate-filter conditions are cast to BOOLEAN.

Additional mappings cover common mathematical functions, array transforms,
base64 strings, maps, URLs, date arithmetic, vector operations, and statistical
aggregates. The printer removes ClickHouse `GLOBAL` distribution modifiers from
joins and membership tests. Trino plans data distribution for these operations.

`test_tracks_every_registered_function_without_a_trino_mapping` snapshots every
registered function that has no Trino mapping. The snapshot separates scalar,
aggregate, and PostHog functions. A new registry function must receive a mapping
or appear in this explicit gap inventory.

The registry has 1,180 names. Trino mode maps 850 of these names. The explicit
gap inventory has 330 names: 149 scalar functions, 155 aggregate functions, and
26 PostHog functions. Aliases count as separate names.

Some workarounds need additional rules. `arrayResize` supports an explicit fill
value. Its two-argument form uses the resolved array item type to supply the default value.
Unknown item types keep an explicit error. `generateSeries` stays unsupported because it is
a table function, while a scalar `sequence` result would change the row shape.
Array index functions apply their predicate with `transform` because Trino does
not have `find_first_index` or `find_last_index`. Bit shifts use Trino's two-
argument signatures, and signed right shifts use the arithmetic variant.

`JSONExtractKeysAndValues` converts values individually and excludes entries that
cannot be converted, so a mixed JSON object does not fail a numeric extraction.
Typed `JSONExtract` maps convert individual scalar values too, but retain keys
and use the requested type's default for values that cannot be converted.
`splitByChar`/`splitByString` support an optional maximum substring count with the
ClickHouse default behavior of excluding the remaining suffix.

`parseDateTimeBestEffort` supports ISO timestamps with explicit offsets, ordinary
date/timestamp strings, day-abbreviated-month-two-digit-year strings, and 9–10 digit Unix-second strings. An optional timezone
controls interpretation of unzoned strings and the returned wall-clock timestamp.
Other ClickHouse best-effort formats remain unsupported at execution; invalid
strings raise an error rather than becoming NULL. `toStartOfInterval` supports
positive constant intervals from seconds through years. It also supports a custom
origin. Hour intervals without an origin reset at the start of each day.

Two-argument `floor`/`ceil` scale by a power of ten before rounding, using Trino
floating-point arithmetic. `roundBankers` supports constant precision from -18 to
18, using decimal rounding increments and ties-to-even correction. Its input is
evaluated once, outside the correction lambda, so aggregate arguments remain valid.
`intDiv` supports integer operands through BIGINT division without floating-point
conversion. Non-integer operands remain rejected. `median` uses `approx_percentile`
at 0.5, following the existing approximate `quantile` translation; the algorithms
do not guarantee identical estimates between engines.

URL query, fragment, path, and parameter functions preserve percent-encoded text.
`extractURLParameter` returns the first matching parameter, or an empty string when absent.
The URL parameter array functions keep duplicates and parameters without values.
`arrayZip` supports two to five arrays.
Dynamic arrays receive an equal-length guard instead of Trino's NULL padding.
The regex group functions support constant patterns with 1–20 capture groups.
They support one-match, vertical, and horizontal result shapes.
`regexpExtract` supports a constant pattern and an optional constant group index.
`replaceRegexpOne` supports constant
patterns and replacements, including numbered replacement captures. Lookarounds,
inline flags, and pattern backreferences remain rejected for first-only replacement.
These regex translations use Trino's regex engine, so engine-specific regex syntax
is not universally portable.

Extended decimal arithmetic (`multiplyDecimal`/`divideDecimal`), additional hash
algorithms, full public-suffix domain rules, and frame-sensitive window functions
still require their own compatible implementations; these mappings do not remove the
existing rejection guards.

Additional build-oriented mappings cover UTF-8 string aliases, URL encoding,
array enumeration and predicates, supported hashes and domain extraction, UUID
conversion, dynamic JSON paths, and scalar tuple membership. Numeric
and UUID values are aligned with string branches in subqueries and set operations.
Date/time inputs to `toFloat` and `_toUInt64` use Unix epoch conversion rather than
casts that Trino rejects.
String rewrites also cover byte-based `locate`, Unicode tokens, subsequences,
ASCII case folding, form URL encoding, regex quoting, and `initcap`.
The IPv4 rewrites cover validation, integer conversion, text conversion, CIDR membership, and CIDR ranges.
IPv6 support currently covers validation and CIDR membership.
Constant `defaultValueOfTypeName` calls support primitive, nullable, array, and string-keyed map types.
The date rewrites now include `dateName`, slots, time extraction, integer Unix timestamps, and interval arithmetic.
Token predicates use ClickHouse's ASCII token boundaries and ASCII-only case folding.
`netloc` preserves user information, ports, and scheme-free authority strings.
URL hierarchy functions preserve path, query, and fragment boundaries for absolute URLs.
`cutURLParameter` removes the first matching key/value parameter and keeps URL delimiters.
XML component functions support named entities and decimal or hexadecimal numeric entities.
`JSONType` supports up to five constant or dynamic path items and returns ClickHouse type names.
The readable size and quantity functions preserve source units, rounding, NaN, and infinity output.
`roundToExp2` uses exact bit shifts for integers and signed powers for floats.
`gcd` and `lcm` use a bounded Euclidean reduction and preserve zero-input errors.
`date_bin` supports positive constant intervals from seconds through years with a custom origin.
It rejects a timestamp before its origin, as the ClickHouse expansion does.
`arrayAUC` uses a sorted linear scan with exact tie handling and nonzero positive labels.
`UUIDv7ToDateTime` reads the 48-bit Unix millisecond prefix.
The timestamp constructors truncate fractional seconds and preserve named timezone instants.
`tupleToNameValuePairs` uses resolved tuple field names and evaluates its tuple once.
`pointInEllipses` supports one or more inclusive ellipses.
`ifNotFinite` now has its correct two-argument registry contract.
`sortablesemver` returns three numeric parts or a nullable invalid sentinel.
`ngrams` uses Unicode character positions. Token-array predicates require at least one valid token.
Map-form `mapPopulateSeries` supports a source map and optional maximum key.
IPv4 substring extraction preserves the source handling of invalid leading octets.
The four `maxIntersections` forms use a half-open endpoint sweep.
They return the first position that reaches the maximum and support window clauses.

Select aliases used by generated `UNNEST` table arguments are expanded before the
query is re-resolved. Dynamic `mapFromArrays` inputs retain their original keys and
fail when Trino cannot represent duplicate or null keys.
The n-gram rewrites use byte four-grams or Unicode three-grams. Search divides
the multiset intersection by the second argument's gram count. ASCII-insensitive
forms use ASCII case folding. Unicode case-insensitive forms remain unsupported.
`cityHash64` remains unsupported because Trino does not provide its exact algorithm.

`accurateCast` and `accurateCastOrNull` reject fractional integer conversions and
unsigned overflow. `base58Encode` uses an arbitrary-length digit array, so it does
not lose large inputs. `format` supports constant templates with empty placeholders,
escaped braces, and values that have the same text form in both engines. HogQL's
`to_char` alias uses the existing `formatDateTime` handler. `bar` preserves the
one-eighth horizontal block output.

The week rewrites support all ten ClickHouse week modes. `toStartOfWeek` supports
the related Sunday and Monday starts. `toStartOfISOYear` computes the Monday that
starts the ISO year. `timeZoneOffset` uses the timestamp's stored zone offset.

The remaining function gaps fall into these groups:

- ClickHouse aggregate states, remaining combinators, bitmap aggregates, and specialized
  estimators have no portable Trino state format.
- H3, bitmap, remaining IP, and block-level functions need connector functions or target
  types that the compiler manifest does not guarantee.
- Remaining tuple, map, and array functions that depend on a dynamic return type need
  type-aware AST lowering. A string-only function handler cannot preserve them.
- Table functions, including `generateSeries`, need relational lowering. A
  scalar array workaround would change the number of result rows.
- PostHog display functions produce HogQLX output instead of relational values.
  Other PostHog functions must expand before the detached Trino compiler runs.
- Exact hashes, quantiles, regex engines, and public-suffix functions stay blocked
  when a similar Trino function has different results.

### Aggregate and typed function rewrites

`avg`, `sum`, `min`, `max`, `count`, `countDistinct`, and `median` support the registered `OrDefault`, `OrNull`, `Array`, `ForEach`, `Map`, `ArgMin`, and `ArgMax` combinations, including `If` suffixes.
Standard `FILTER` predicates combine with `If` predicates.
The compiler distinguishes an empty group from a group that contains an empty array.
Nullable values keep their null defaults. `avgArray` keeps HogQL's `avgArrayOrNull` mapping.
For window calls, HogQL prints the native `avgArray` name. Its empty non-null input result is NaN, not NULL.
Array aggregates collect values within each group before reduction. Large groups can require substantial memory.
Numeric array reductions require integer or float items. State and merge combinators remain separate gaps.
These aggregate forms also support window clauses. Additional aggregate modifiers retain explicit errors.

`ArgMin` and `ArgMax` aggregate every value tied at the extreme selection key.
Null values and null keys do not select the extreme key. The one-argument `count` form counts keys alone.
Selection keys can be integers, floats, strings, dates, timestamps, or booleans.
NaN selection keys and NaN values for `min` and `max` retain runtime errors.
UUID and container selection keys remain blocked because their ordering needs additional checks.

`medianExact`, `medianExactLow`, and `medianExactHigh` support plain and `If` forms, including window clauses.
Exact quantiles and medians exclude null and NaN input values.
Empty integer and date inputs use their type defaults. Empty float inputs return NaN.
Nullable inputs return NULL when no non-null value passes the filter. An input with only NaN values returns NaN.
Low medians select the lower middle value. Exact and high medians select the upper middle value.

The `median` combinator family uses exact interpolation between the two middle values.
It supports aggregate and window forms. It also excludes null and NaN values.
Empty Map and ForEach results remain non-null containers, including `OrNull` forms.
ClickHouse uses a reservoir estimator for large inputs, so large-group estimates can differ.

`medianExactWeighted` and `medianExactWeightedIf` support aggregate and window forms.
They accept numeric or date values with non-negative integer weights.
They exclude null values and NaN values. A negative weight raises an error.

`quantiles` and `quantilesIf` accept one or more constant percentiles from zero through one.
They return a Trino `approx_percentile` array and exclude null and NaN values.
An empty result contains one NaN for each requested percentile.
The two engines can produce different approximate estimates.

`avgWeighted` and `avgWeightedIf` support aggregate and window forms.
They exclude a row when its value or weight is null. Empty nullable inputs return NULL; other empty inputs return NaN.
Float weights support negative values and weights. A zero weight sum can produce infinity or NaN.
Integer weights require non-negative finite values and non-negative weights. Fractional values truncate before multiplication, as in ClickHouse.
Integer sums and products must fit a signed 64-bit integer. Overflow fails instead of applying an uncertain unsigned wrap rule.

`skewPop`, `skewSamp`, `kurtPop`, and `kurtSamp` use ClickHouse's raw-moment formulas.
`simpleLinearRegression` uses the same five accumulated values as ClickHouse.
These functions support `If`, aggregate filters, null values, empty groups, and window frames.

`groupUniqArrayArray` flattens arrays, removes null values, and keeps distinct values.
Its optional positive limit and its `If` form also work in window frames.
`groupArrayInsertAt` creates typed defaults for missing positions and removes null inputs.
Positions above Trino's array limit retain an explicit error.

`groupArrayMovingSum`, `groupArrayMovingAvg`, and `deltaSum` retain input-order semantics.
Their `If` forms and window forms are supported.
Plain aggregate calls can differ when the two engines process unordered rows differently.
Use a window with an `ORDER BY` clause when the result requires a stable order.

`ForEach` aggregates each array position across the group. Shorter arrays do not supply a value for a missing position.
`Map` aggregates each key across the group and sorts the output keys.
These two families return empty containers for empty groups, including `OrNull` forms.
Map inputs must already have a Trino-compatible map type. Legacy map forms with separate key/value arrays remain blocked.
`arrayReduce` supports constant `count`, `sum`, `min`, `max`, and `avg` names, and their `Map` variants.
Other aggregate names and aggregate states retain explicit errors.

`arrayCumSum` and `arrayCumSumNonNegative` support one array and an optional single-argument lambda.
Cumulative values require non-null integer or float types. Fractional lambda results use floating-point accumulation.
`arrayFill`, `arrayReverseFill`, `arraySplit`, and `arrayReverseSplit` support one array and one predicate lambda.
The rewrites preserve the first or last element, null values, empty arrays, and the direction of each split.
Scans build intermediate arrays. Large arrays can require substantial copying and memory.

`LpNorm` and `LpDistance` support non-null numeric arrays and tuples. Distance inputs must have equal lengths and the same container type.
The four normalization functions support numeric tuples, matching the source functions' input contract.
Their results contain floating-point values. Zero norms preserve NaN results.
Lp exponents below one or infinite exponents raise an error. A NaN exponent keeps its NaN result.
Floating-point results can differ at machine precision between engines.

`factorial` accepts integers no greater than 20. Inputs at or below zero return one.
`roundAge` and `roundDuration` use the source engine's fixed buckets.
`roundDown` requires a non-empty boundary array and preserves a NaN input.
These numeric functions preserve null inputs.

Tuple addition, subtraction, multiplication, division, negation, and scalar multiplication/division use resolved tuple sizes.
Arithmetic supports integer and float items. Division uses floating-point arithmetic.
Tuple Hamming distance preserves null comparison results.
`arrayLast` uses the resolved item type for the no-match default. `arrayFirst` also preserves nullable defaults.

The `multiSearch` position, index, and predicate families have byte-position and UTF-8 rewrites.
First index means the first matching needle in input order, not the earliest position in the text.
Empty text, missing matches, and empty needle lists keep their separate results.
Byte-based case-insensitive search folds ASCII letters only.
UTF-8 case-insensitive search rejects text or needles whose lowercase conversion changes a character's byte length, because engine behavior differs for these characters.

Trino set operations retain the types of unnamed branch expressions.
This prevents a non-null UNION column from receiving a nullable aggregate default.
Trino division also receives a floating-point result type, so cumulative lambdas do not use an integer accumulator for fractional values.

### Relational compatibility rewrites

The ASOF result test uses one DuckDB thread.
Repeated parallel execution on DuckDB 1.5.2 dropped duplicate rows and crashed for the generated nested-window query.
The same SQL passed repeated single-threaded DuckDB and Trino checks.
This test setting does not change production SQL or Trino execution.

The compiler rewrites these forms before it prints Trino SQL:

- `QUALIFY` can contain inline window functions and unprojected predicate fields.
  Helper columns stay inside the generated subqueries. The compiler preserves
  the original output columns and applies `DISTINCT` after the predicate.
- `QUALIFY` can precede `LIMIT BY`. Window expressions in `LIMIT BY` partitions
  or ordering run in a separate input stage. The final limit runs last.
- `UNION ... BY NAME` aligns resolved columns before type unification. Trino also
  accepts uniform `INTERSECT` and `EXCEPT` chains by name. Every branch must have
  the same unique column names. Mixed operator families require explicit
  subqueries. The compiler preserves positional references when it reorders columns.
- Equi-key `SEMI` joins use a distinct right-key relation. `ANTI` joins use a left
  join to that relation and test an equality key for null. Both preserve duplicate
  left rows. Right-side output references and computed right keys remain blocked.
- Two-table `RIGHT ANY`, `RIGHT SEMI`, and `RIGHT ANTI` joins reverse their inputs
  before the existing left-side rewrite. Longer right-join chains remain blocked.
- Two-table `INNER ASOF` and `LEFT ASOF` forms use a join followed by ranking.
  The constraint needs equality keys and exactly one field-to-field inequality.
  Each left input row gets an internal identifier, so duplicate left rows survive.
  Input columns must be complete. Subqueries outside the inputs and indirect
  output properties remain blocked. Equal nearest timestamps have no specified
  tie order. Candidate joins can be large; use selective keys and bounded inputs.
- Static `PIVOT` uses filtered aggregates. This version accepts one key and one
  `count`, `sum`, `avg`, `min`, or `max` aggregate. Pivot values must be string or
  integer constants. Output aliases are supported; duplicate names are rejected.
- `UNPIVOT` uses one input scan and an array of rows. It preserves the null mode.
  This version accepts one scalar value/name pair and field inputs. Tuple outputs,
  input aliases, multiple column groups, and incompatible value types remain blocked.
- `LEFT ARRAY JOIN` inserts a typed default row when the input arrays are empty.
  Supported defaults include strings, integers, floats, booleans, nullable items,
  arrays, and supported tuples. Other item types keep explicit errors. Multiple
  arrays still need equal lengths. Internal `ARRAY JOIN` ASTs can omit `FROM`,
  although the source parser can reject that form.
- A constant percentage limit uses counting and ranking after the input query.
  It rounds up and calculates the row count before the offset. Percentages must
  be between zero and 100. Percentage limits with ties remain blocked. This also
  supports internal `limit_percent` ASTs when a parser does not accept `PERCENT`.
- Integer addition, subtraction, and multiplication can supply `LIMIT`, `OFFSET`,
  and `LIMIT BY` counts. Arithmetic must stay within the signed 64-bit range.

The Trino printer preserves `FILTER` on the standard aggregates used by `PIVOT`
and on `countDistinct`. Filter values use the existing predicate conversion.

`WITH FILL`, `INTERPOLATE`, `FINAL`, nontrivial `SAMPLE`, `POSITIONAL JOIN`, and
recursive `USING KEY` still have no general rewrite. Complex ASOF forms, full ANY
joins, dynamic pivot schemas, and set-query limits with ties also retain explicit
errors. The compiler does not remove clauses or switch execution engines silently.

Run the Trino printer, semantic expansion, and parameter-helper tests. Run the existing printer/resolver and direct-adapter tests to check shared behavior, and the startup-import guards to check initialization. Do not regenerate existing dialect snapshots simply to make a regression pass.

Compilation success is not proof of target schema compatibility or equivalent results. Validate printed SQL separately against the intended Trino schema and compare results only where the source and target data are comparable.
