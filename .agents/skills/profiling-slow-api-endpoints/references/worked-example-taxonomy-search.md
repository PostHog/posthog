# Worked example: taxonomic filter search

The definitions search behind the taxonomic filter returned in seconds. It now
returns in tens of milliseconds for almost every project. The fix landed in
[#95749](https://github.com/PostHog/posthog/pull/95749), and the code sits in
`posthog/taxonomy/definition_search.py`.

It is a useful example because the obvious fix was wrong, and only step 4 of
the loop showed why.

## 1. The evidence

APM gave a p95 of 13.6 s on the events tab and about 7.5 s on the event and
person property tabs. The time sat in the definitions list query, not in
rendering.

## 2. The plan

Both list endpoints searched names with `ILIKE`. Postgres answered that from
the trigram index on `name`, which covers every project at once. For a longer
search term the planner read trigram posting lists for the whole table and
then intersected them with the project's rows.

That cost does not depend on the size of the project. A small project paid for
the whole table.

`EXPLAIN (ANALYZE, BUFFERS)` on the read replica showed the planner's choice
followed the search term, not the project:

| Query on a mid-size project | Plan picked           | Time     |
| --------------------------- | --------------------- | -------- |
| events, `%page%`            | project-scoped index  | 42 ms    |
| events, `%session recording%` | global trigram index | 3,485 ms |
| properties, `%current url%` | global trigram index  | 2,826 ms |

Writing the predicate as `lower(name) LIKE lower(pattern)` is a form no
trigram index can serve, so the planner starts from the project-scoped index
instead. The same queries then took 9 ms and 39 ms.

The paginator count runs the same predicate, so every request paid this twice.

## 3. Why the obvious fix was wrong

Applying the rewrite everywhere looked like a free 70x to 380x win. Sizing the
table across the fleet showed it was not:

- The project scan costs about one page per row.
- The trigram path costs roughly 15k to 25k pages per trigram in the term.
- The two are level somewhere around a few hundred thousand rows.
- Almost every project sits far below that. A few sit far above it, and for
  those the rewrite is much worse.

So the rewrite had to apply to small projects and stay off the largest ones.

## 4. The shape of the fix

- Below `PROJECT_SCAN_MAX_DEFINITIONS` (50,000) definitions in the table, use
  `lower(name) LIKE lower(pattern)`. Above it, keep `ILIKE`.
- The decision comes from a bounded count (`LIMIT 50001`) on the
  project-scoped index, cached for 24 hours per table and project.
- The cache read and write go through the safe helpers, so a Redis failure
  costs one count query per request instead of a 5xx.
- A stale answer only changes query time, never results.
- The chosen plan lands on the current span as `taxonomy_search_plan`, so the
  effect is visible per request in APM.
- The threshold is deliberately conservative. The project scan still won by
  about 40x well above it, so there is headroom on the side where being wrong
  is expensive.

## 5. What the tests had to catch

Result-based tests pass either way, so they prove nothing here. The tests
assert the mechanism:

- the predicate switches form with the flag and keeps identical parameters
- the plan follows the count against the threshold, and is cached per table
  and per project
- the plan still returns when the cache read or write raises
- both endpoints emit the predicate form the plan asks for

The existing definition API suites ran on a devbox against Postgres.

## Related

A second, independent win in the same area needed no database work:
[#95609](https://github.com/PostHog/posthog/pull/95609) stopped the picker
holding results back while a separate request counted matches outside the
selected events. `docs/internal/taxonomic-filter-search.md` is the behavior
contract for that.

An earlier attempt, [#95647](https://github.com/PostHog/posthog/pull/95647),
applied a project-first plan unconditionally behind a flag and was closed
without merging. It regressed large projects, which is the step-4 lesson.
