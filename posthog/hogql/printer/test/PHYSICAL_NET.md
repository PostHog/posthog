# Physical-optimization result-equivalence net

Index of the tests that gate the ClickHouse **physical** optimizations during the HogQL printer rearchitecture
(see `posthog/hogql/PRINTER_REARCHITECTURE.md`, esp. §9.4 and §12.6).

Why this net exists: the rearchitecture moves property→physical-SQL decisions out of the ClickHouse printer and into
explicit AST passes. The rewrites are **result-equivalent, not byte-identical** — the SQL text churns. So golden SQL
text is only a per-PR tripwire; the real correctness gate is **execution results + skip-index `EXPLAIN`** (and, on the
one path where form is load-bearing, the lightweight-DELETE-mutation constraint). This file lists, in one place, every
test that forms that gate, so a reviewer can see the full net at a glance.

Everything here runs against a live ClickHouse and passes on **master**.

## Existing net (the bulk of the coverage — do not duplicate)

### Skip-index `EXPLAIN` matrix — `posthog/hogql/test/test_property_skip_indexes.py`

A `_PropertySkipIndexTestBase` (`_run_explain_and_get_skip_indexes`) sweeps scope × skip-index × materialization ×
operator, asserting *which skip indexes the query plan uses*:

- `TestEventPropertySkipIndexes` — event properties: JSON-only (no index), minmax (nullable / non-nullable),
  bloom-filter, ngram-lower (`lower(...) IN`), range (`<` lexical + typed numeric/datetime), property groups
  (`test_property_group_optimized`), dmat (`test_dmat_string_no_skip_indexes`).
- `TestPersonOnEventsPropertySkipIndexes` — the same matrix for person properties in PersonsOnEvents mode.
- `TestPersonPropertySkipIndexes` — the same matrix for person properties read through the person join.

### Materialized-column rewrite results + index usage — `posthog/hogql/printer/test/test_printer.py`

`TestMaterializedColumnOptimization` (`ClickhouseTestMixin`, `APIBaseTest`) asserts both *result rows* and *index use*
(`get_index_from_explain` / `get_minmax_index_name` / `materialized()`), covering the printer's comparison optimizers:

- equality / range optimization returns correct results + minmax index
  (`test_materialized_column_optimization_returns_correct_results`,
  `test_materialized_column_range_optimization_returns_correct_results`).
- ILIKE / LIKE / NOT-ILIKE / NOT-LIKE — raw column + ngram-lower index, sentinel bail-outs.
- IN / NOT IN — `has([...], col)` flip, bloom-filter / ngram-lower-index, nullable sentinels
  (`test_in_and_not_in_optimization_gives_correct_results`, `test_lower_in_optimization_handles_null_and_sentinel_rows`).
- the non-optimization cases (empty-string / `"null"` / null-comparison / non-string constant) that must NOT fire.
- `$session_id` real-column minmax optimization (`test_session_id_uuid_uses_minmax_index`) — note this optimizes a real
  column, not a property; the doc leaves its placement in the stack open (§11.2).

These two files are the documented physical gate. New work should reference them, not re-implement them.

## New tests added in PR0c (this directory)

### `test_property_characterization.py`

- `TestPersonPropertyIsNotSet` — is_not_set over a **person** property across PersonsOnEventsMode (joined vs on-events)
  × materialized vs not. Locks §8.2: a non-nullable materialized column stores `''` for both empty-string and missing,
  so it cannot represent "is set" (empty string collapses to NULL once materialized). Asserts the value/flag results
  for email set / empty-string / null / absent, plus that the materialized path emits no JSON/`Has` op on the blob.
  This also exercises the master path that correctly resolves a person-joined materialized column
  (`ClickHousePrinter._get_table_name` → `to_printed_clickhouse`).
- `TestPhysicalScenarios` — drives `PHYSICAL_SCENARIOS` from `property_corpus.py`: materializes the named column(s),
  inserts match/no-match events, runs the HogQL, asserts result rows + (for index-eligible cases) the expected minmax
  skip index. Includes the `mat_is_not_set` footgun (§8.2) in **execution** form: `properties.test_prop IS NULL` over a
  non-nullable materialized column. NOTE — the corpus `description` for that scenario states the rearchitecture
  *target* (decline onto the blob); this test instead **locks current master behavior**, which is the footgun itself:
  master reads the scrubbed mat column (`isNull(nullIf(nullIf(mat_test_prop, ''), 'null'))`), so empty-string and the
  literal `"null"` string both collapse to "not set". The test makes the divergence from the truthful JSON-blob answer
  explicit and machine-checked, so when the rearchitecture flips the behavior the expectation flips with it.

### `test_within_non_hogql_delete.py`

- `TestWithinNonHogqlDelete` — the genuinely missing §8.4 net. Compiles `properties.$browser = 'Chrome'` via
  `compile_hogql_predicate` (`posthog/models/data_deletion_request.py`) **with `$browser` materialized**, asserts the
  fragment is **unqualified** (no `events.` / `sharded_events.` prefix on the mat column — the lightweight-delete
  mutation analyzer rejects qualified names) and uses only mutation-safe scalar functions, then runs a **real
  lightweight `DELETE` mutation** against the test `sharded_events` table using that fragment (mirroring production's
  `LightweightDeleteMutationRunner` statement + settings) and asserts the matching rows are gone while non-matching and
  other-team rows survive. Both the materialized and the JSON-blob fragment shapes are covered.

  Why it's new: `posthog/dags/tests/test_data_deletion_requests.py` already runs the full `compile_hogql_predicate` →
  delete flow, but only over an *unmaterialized* property — none exercise the materialized-column + unqualified
  requirement that §8.4 is about. This path is high-volume in production.
