# TaxonomicFilter performance

Use this reference when you change TaxonomicFilter search, loading, pagination, or result reveal behavior.
For the full profiling workflow, use [`profiling-slow-api-endpoints`](../../profiling-slow-api-endpoints/SKILL.md).

## Where users wait

Measured with `taxonomic filter search latency` (`time_to_see_data_ms`).
Refresh with query 9 in [refreshing-product-reality](refreshing-product-reality.md).

- The median search is fast (~200ms) in every large group.
- The slow tail is concentrated.
  Persons search has a p90 of ~4s and a p99 over 10s.
  Pageview URLs have a slow p99.
- Customers rarely report slowness.
  Failures that look like loading or like "no results" hurt more (see below).
  Rank latency work against [failure-modes](failure-modes.md), not on its own.

## A failed request must show as an error

`taxonomic filter fetch failed` fires ~0.2 times per 100 search queries (query 10).
One search can send several events, so this is not a share of failed searches.
The health dashboard shows ~2%, but it divides every failure, first loads included, by timed searches, so it overstates the rate.
Cohorts, events, person properties and flags make up most of the failures.
Loading ends on a failure and shows "Couldn't load results" with a retry, except for a 403.
A 403 must not look like "no results".

- `InfiniteListErrorState` in `InfiniteList.tsx`, fed by `infiniteListLogic.ts`.
  Its `remoteFetchForbidden` shows an access-denied message with no retry for a `permission_denied` 403.
- Keep `taxonomic filter fetch failed` firing with `groupType` and `searchQuery`.

## Backend search plan

The definition search can use two Postgres predicate forms.
`posthog/taxonomy/definition_search.py` selects the form from the number of definitions in the project.
Read the current helper and threshold before you change this path.

The conditional plan exists because one index strategy does not perform well for every project size.
A global trigram index can make a small project scan index data for all projects.
A project-scoped scan can become expensive for a very large project.

Keep these properties unless new measurements support a different design:

- The size check is bounded and cached per table and project.
- A stale cache value changes performance, not results.
- A cache failure does not fail the request.
- The selected plan is recorded as `taxonomy_search_plan` on the request span.
- The paginator count and result query use the same search form.

When you add a searchable column or change a predicate, compare the exact endpoint SQL for both plan forms.
Measure projects on both sides of the threshold.

## Frontend result reveal

`docs/internal/taxonomic-filter-search.md` is the source of truth for result reveal behavior.
Do not restate its loading rules here.

For performance work, measure the time until the first usable result.
Check `infiniteListLogic.ts` for how loading is implemented.

## Verification

- Use an APM trace from a real TaxonomicFilter open.
- Compare both Postgres predicate forms with safe production `EXPLAIN` queries.
- State whether each measured query used a warm or cold cache.
- Run the definition API tests against Postgres.
- Test the loading path, including a failed request.
- After shipping, compare p90 and p99 by group and the fetch failure rate.

Result tests alone do not protect the plan choice because both plans return the same rows.
When plan selection changes, test the boundary, cache failure, and SQL shape.
Verify both definition endpoints when they share the changed helper.
