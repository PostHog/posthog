---
name: authoring-data-quality-checks
description: >
  Adds and runs data quality checks (dbt-test style assertions) on a project's warehouse tables and
  saved-query views, and HogQL catalog metrics: not-null, uniqueness, accepted values, referential
  integrity, row-count bounds, freshness, and custom HogQL. Metrics support custom SQL checks only.
  Use when asked to test a model, validate a view, check for nulls or
  duplicates, add data quality checks, find out why a number looks wrong, or judge whether a warehouse
  table is trustworthy before using it in an analysis. To describe what data *means* (metrics,
  certifications, joins), see setting-up-data-catalog instead. Trigger terms: data quality, data test,
  dbt test, not null check, uniqueness check, freshness check, referential integrity, row count check,
  validate model, is this table trustworthy.
---

# Authoring data quality checks

A check is one assertion about one warehouse table, view, or HogQL catalog metric. It compiles to a
count-only HogQL query and **passes when it finds zero failing rows**, like `dbt test`. Failing rows are
never stored; only counts and the compiled query are, so to see the offending rows you re-run the
stored query yourself.

`row_count` is the exception. It passes when the observed count is within its configured min/max
bounds, so its `failed_row_count` comes back null and its stored query returns that single count,
not offending rows. Read the observed count to judge it rather than looking for matched rows.

Reads go through SQL (`system.information_schema.data_quality_*`); writes and runs go through the
data-quality MCP tools.

## Before you write anything: look

Two queries save you from the two most common mistakes — duplicating a check, and checking a column
that doesn't exist.

```sql
-- What is already covered?
SELECT name, subject_name, column_name, check_type, config, severity, last_status
FROM system.information_schema.data_quality_checks
WHERE subject_name = 'orders'

-- What columns are there, and what do they mean?
SELECT column_name, data_type, description
FROM system.information_schema.columns
WHERE table_name = 'orders'
```

Re-creating a byte-identical check is a harmless no-op — checks are keyed by a fingerprint of the
subject, type, column, and config, so an identical create upserts. A _near_-duplicate is not
harmless: it doubles the noise for whoever reads the results. If an existing check's assertion is
close but wrong, edit the existing check. Updates preserve its identity and history; the subject
stays fixed by the URL. An edit that duplicates another check's assertion is rejected.

## Choosing checks

Aim for a handful that would actually catch a real regression, not blanket coverage. A model with
twenty checks nobody reads is worse than three that fail meaningfully.

Reach for these first, in roughly this order:

- **`not_null` on the columns downstream joins and filters depend on.** The single highest-value
  check. A null join key silently drops rows.
- **`unique` on whatever the model claims is its grain.** If `orders` is one row per order, say so.
- **`relationships` on foreign keys.** Catches the join that quietly stopped matching after an
  upstream change.
- **`accepted_values` on status and category columns** whose downstream logic branches on them.
- **`freshness` on the timestamp column of anything that syncs.** Catches a dead pipeline, which no
  row-level check will.
- **`row_count` bounds** when you know the plausible range. Good for catching a truncated sync.
- **`custom_sql`** only when nothing above expresses the invariant — e.g. cross-column arithmetic
  (`select 1 from orders where total != subtotal + tax`). Every row it returns counts as a failure.

Call `posthog:data-quality-check-types` for each type's exact config schema rather than guessing.

Checks live on the subject they audit: create them with `data-quality-check-create-on-view`
(`saved_query_id` path parameter) or `data-quality-check-create-on-table` (`table_id`).

## Checks on catalog metrics

Only metrics with a saved `HogQLQuery` definition support checks. Markdown, Trends, Funnels, event
series, and metrics without definitions do not. A metric can return any number of rows and columns.

Create a `custom_sql` check with an empty `column_name`. Include `{metric}` exactly once as a relation:

```sql
SELECT *
FROM {metric}
WHERE orders < 100
```

The check queries the owning metric's current saved output. The example assumes that output has an
`orders` column. Every returned row is a failure; zero rows passes. Query `{metric}` directly or
through a subquery. Metric check SQL cannot define CTEs, including nested CTEs and scalar `WITH`
bindings. CTEs and saved parameters inside the metric definition remain supported. Other placeholders
are not accepted in the check.

Use the metric's Tests tab or the nested REST endpoints under
`/api/projects/{project_id}/data_catalog/metrics/{metric_id}/checks/`. The catalog metric detail
endpoint uses the metric name, but nested check endpoints use its UUID. The metric check-type
endpoint offers only Custom SQL. Do not assume the table/view MCP tools accept metric subjects.

Saving validates SQL composition without executing it. Run the check to verify column names and
results. Every run reloads the saved metric: if an edit removes a column used by the check, the next
run errors. Fix the check SQL or restore the expected metric output.

## Severity and triggers

**Severity** is a decision about consequences, not about confidence. Use `error` when the failure
means downstream numbers should not be trusted — those failures mark the subject `failing` and
notify. Use `warn` for things worth surfacing that nobody would act on today. When unsure, `warn` is
the safer default: an `error` check that cries wolf gets everything ignored.

**Table and view triggers:** A check runs when its subject's data changes: a
materialized view's checks run as part of its refresh (and, when the team turns the gate on, a
refresh whose error-severity checks fail is not published), a source table's checks run after each
completed sync, and a plain view's checks run when its DAG runs. Checks on a view outside any DAG
only run on demand.

**Metric schedules:** The first saved check creates an enabled daily schedule for all checks on the
metric. The Tests tab lets you change the interval or turn automatic runs off. Manual runs remain
available. Scheduled checks use the latest definition author's access, falling back to the creator;
manual runs use the initiating user's access. Underlying and additional tables must be readable.

Temporal owns each metric's cadence and pause state. Paused schedules have no next execution time.
Reload after an unavailable schedule response before retrying an edit; the edit may have succeeded.
Automatic runs skip overlaps and catch up missed occurrences only within 15 minutes.
Disabling or deleting every check preserves the schedule preferences. Deleting the metric removes its schedule.

## Verify what you wrote

Author, run once, read the result. A check nobody has run is a guess.

1. `posthog:data-quality-check-create-on-view` (or `-on-table`)
2. `posthog:data-quality-check-run-on-view` (or `-on-table`) — returns a suite run
3. Poll `system.information_schema.data_quality_check_runs` (or
   `posthog:data-quality-check-results-on-view`/`-on-table`) for the outcome

A `failed` result on the first run is the interesting case: either you found real bad data, or the
assertion is wrong. Take the `compiled_query` off the run, execute it with `posthog:execute-sql`, and
look at what it actually matched before reporting anything. That `compiled_query` comes from
`posthog:data-quality-check-results-on-view`/`-on-table`; the information_schema poll in step 3 does
not return it. An `errored` result is never a data
problem — the query could not run at all, usually a column name typo or a subject that no longer
exists.

## Judging a source before you use it

When an analysis depends on a warehouse table or view, check its verdict first:

```sql
SELECT subject_name, health, checks_total, checks_failing, last_run_at
FROM system.information_schema.data_quality_health
```

- `failing` — an error-severity check found bad data. Say so in your answer; don't quietly use it.
- `erroring` — a check couldn't run. The data may be fine, but nobody is watching it.
- `warn` — only warn-severity failures. Usable, worth a mention.
- `healthy` — checks ran and passed.
- `unknown` / absent — no checks, or none have run. Absence of failures is not evidence of health.

For the history behind a verdict, `system.information_schema.data_quality_check_runs` carries recent
executions with status, failing-row count, and errors. For metric checks, the failing-row count
describes the assertion result, not a scalar metric value. Open the failing-row query from the
Tests tab to inspect the current rows that violate the check.

## Related

- `setting-up-data-catalog` — what the data _means_: metrics, trust marks, relationships.
- `querying-posthog-data` — the schema-discovery and HogQL rules these queries follow.
