# TaxonomicFilter performance

Use this reference when you change TaxonomicFilter search, loading, pagination, or result reveal behavior.
For the full profiling workflow, use
[`profiling-slow-api-endpoints`](../../profiling-slow-api-endpoints/SKILL.md).

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
Check both `infiniteListLogic.ts` and `hooks/useGroupList.ts` because the legacy and rebuild paths implement loading separately.

## Verification

- Use an APM trace from a real TaxonomicFilter open.
- Compare both Postgres predicate forms with safe production `EXPLAIN` queries.
- State whether each measured query used a warm or cold cache.
- Run the definition API tests against Postgres.
- Test the legacy and rebuild loading paths.

Result tests alone do not protect the plan choice because both plans return the same rows.
When plan selection changes, test the boundary, cache failure, and SQL shape.
Verify both definition endpoints when they share the changed helper.
