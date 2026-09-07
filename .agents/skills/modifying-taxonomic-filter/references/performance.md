# Latency in the TaxonomicFilter

~65% of selections come through search, and the p50 open lasts about 7
seconds. Search latency is therefore not an engineering detail behind the
picker; it is the main path through it. A picker that returns in 3 seconds has
already lost most of that open.

For the general method (APM trace, production query plan, fleet sizing, devbox
verification), use
[`profiling-slow-api-endpoints`](../../profiling-slow-api-endpoints/SKILL.md).
This file covers what is specific to this surface.

## Where the time goes on one open

Two independent costs, with two independent fixes:

1. **The definitions query in Postgres**, per keystroke past the minimum
   query length, for every contributing category.
2. **The reveal barrier in the picker**, which decides how long finished
   results wait for unfinished ones.

Both were seconds in 2026-09 and both are now fixed. Do not undo either.

## Backend: the search plan is conditional

`posthog/taxonomy/definition_search.py` chooses how a `?search=` reaches the
project's rows, because Postgres cannot scope the trigram GIN index on `name`
to one project:

- Small project (at most `PROJECT_SCAN_MAX_DEFINITIONS` rows in that table):
  `lower(name) LIKE lower(pattern)`, which no trigram index can serve, so the
  planner starts from the project-scoped index.
- Larger project: plain `ILIKE`, because the few very large projects are
  faster on the trigram index.

Consequences for anything you change on this path:

- **Do not reintroduce a bare `ILIKE`** on the definitions search path, and do
  not "simplify away" the `avoid_trigram_index` flag on
  `term_search_filter_sql`. It looks like dead complexity and it is the fix.
- **A new searchable column needs the same treatment.** A global index on a
  searched column makes small projects pay for the whole table.
- **The paginator count runs the same predicate**, so every search costs it
  twice. Any saving counts double, and any regression does too.
- **The plan lands on the span as `taxonomy_search_plan`.** Keep that
  attribute; it is how the effect stays visible per request in APM.

The measured before-and-after, the threshold reasoning, and the failed first
attempt are in
[the worked example](../../profiling-slow-api-endpoints/references/worked-example-taxonomy-search.md).

## Frontend: what may hold the first paint

Results wait for the categories that contribute to them, and for nothing
else. In particular the unscoped expansion count, which only decides whether
an expansion option appears **below** the results, must not gate the reveal.
A failed or outdated count leaves the current results usable. Recent and
Pinned never fetch, so they must appear at once with no skeleton.

`docs/internal/taxonomic-filter-search.md` is the behavior contract for this.
Read it before changing loading state, and keep the legacy
(`infiniteListLogic.ts`) and rebuild (`hooks/useGroupList.ts`) implementations
consistent, because neither a lint rule nor a test enforces that parity.

The trap is general and worth naming: **when a secondary request only
decorates a result, never make the result wait for it.**

## Re-measuring

- p95 per tab from the APM trace of a real open, not a local click.
- `EXPLAIN (ANALYZE, BUFFERS)` on the read replica for both predicate forms,
  through
  [`querying-production-databases-via-metabase`](../../querying-production-databases-via-metabase/SKILL.md).
  State whether the cache was warm.
- The definition API suites against a real Postgres on a devbox. Tests over
  SQL strings cannot catch a plan regression.

## Guards to keep

Result-based tests pass whichever plan runs, so the regression guards assert
the mechanism instead: that the predicate switches form, that the plan is
cached per table and per project, that it survives a cache failure, and that
both endpoints use the form the plan asks for. Removing those tests removes
the only thing standing between this surface and the 13-second p95 it had.
