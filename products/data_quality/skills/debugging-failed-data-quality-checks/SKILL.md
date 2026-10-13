---
name: debugging-failed-data-quality-checks
description: >
  Finds out why a data quality check failed or errored, looks at the rows it matched, and recommends
  the fix. Also covers a materialized view refresh that the data quality gate did not publish. Use
  when asked why a check is red, what rows failed, why a view shows "Not published", why a view's
  data is stale after a refresh, or how to get a blocked refresh published. Trigger terms: failed
  check, failing rows, errored check, data quality failure, not published, blocked materialization,
  unpublished refresh, check keeps failing.
---

# Debugging failed data quality checks

A check run ends in one of four states.
Read the state first, because it decides where the problem is:

| Status    | Meaning                                        | Where to look                          |
| --------- | ---------------------------------------------- | -------------------------------------- |
| `failed`  | The query ran and the assertion found bad data | The data, or the assertion itself      |
| `errored` | The query could not run, so nothing was judged | The error text (never a data problem)  |
| `skipped` | The subject is gone                            | Whether the table or view still exists |
| `passed`  | The assertion held                             | Nothing                                |

`row_count` and `freshness` checks judge `observed_value`, not `failed_row_count`.
A failed `row_count` means the count fell outside its bounds.
A failed `freshness` means the newest row is older than the limit.

## When to use this skill

- A check or a subject shows `failed` or `errored` and the user wants to know why
- The user wants to see the rows a check matched
- A materialized view's latest run shows an error that starts with `Not published:`
- A view kept serving old data after a refresh, and the data quality gate is on
- Another skill (`authoring-data-quality-checks` or `auditing-warehouse-view-health`) found a failing check or a blocked view and handed it off

## Available tools

| Tool                                 | Purpose                                                                     |
| ------------------------------------ | --------------------------------------------------------------------------- |
| `posthog:data-quality-check-results` | A check's recent runs, with `compiled_query`, `error` and the config it ran |
| `posthog:execute-sql`                | Re-run a run's `compiled_query` to see the failing rows                     |
| `posthog:data-quality-check-run`     | Run a check now                                                             |
| `posthog:data-quality-check-update`  | Fix an assertion or change its severity                                     |
| `view-get`                           | A view's definition and status                                              |
| `view-run-history`                   | A view's materialization runs and their errors                              |
| `view-run`                           | Materialize a view again                                                    |

To find the failing checks, query `system.information_schema.data_quality_checks` for `last_status IN ('failed', 'errored')`, or `system.information_schema.data_quality_health` for a subject's verdict.

## Workflow

### Step 1: Read the run

Call `posthog:data-quality-check-results` for the check.
On the newest run, read:

- `status` and `error`
- `check_config` and `check_severity`: what the run asserted, which can differ from the check today
- `compiled_query`: HogQL that selects the failing rows. For `row_count` it returns the count instead, so judge that check by `observed_value`.
- `audited_staged_refresh`: true when the run was part of a gated audit of a refresh before it was published. An errored run can carry it too, so read `status` first.

Retention clears `compiled_query` after 30 days.
For an older run, run the check again.

### Step 2: Look at the failing rows

Run `compiled_query` with `posthog:execute-sql`.
An empty `compiled_query` means there is nothing to replay: retention cleared it, or a gated run could not read the view's definition.
Look at what it matched before you report anything.
A failure means one of two things: the data is bad, or the assertion is wrong.
The rows tell you which.

When `audited_staged_refresh` is true, the query does not read the published table.
It holds the view's definition in a `WITH` clause and reads the view's source tables now.
The sources may have changed since the run, so the rows and the count can differ from the run.
A query that now returns zero rows does not prove that the refresh was clean.
Compare with `failed_row_count` on the run.

### Step 3: Read an errored run

An errored run did not judge the data.
Match the error text:

| Error text                                                          | Cause and fix                                                                                                                                                        |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `The staged files could not be read, so this data was not audited.` | The gate could not reach the refresh before publish. The refresh publishes without a verdict. Run the view again.                                                    |
| `Metric checks cannot audit staged data.`                           | A metric check was part of a gated refresh. It runs on its own schedule instead.                                                                                     |
| `The check query returned no rows.`                                 | The aggregate query returned nothing. Run the check again and report it if it repeats.                                                                               |
| `A check that reads another subject needs an initiator or author…`  | An automatic run of a `custom_sql` or `relationships` check has no user to run as. A manual run works. An edit to the check's assertion makes the editor its author. |
| A HogQL or ClickHouse error                                         | A column name typo, a type mismatch, or a query that ran out of time. Fix the config, or add `lookback_hours`.                                                       |

Two messages come with `skipped`: `The subject was deleted.` and `The subject no longer resolves.`
The table or view is gone.
Delete the check or point it at the replacement.

### Step 4: Understand a blocked refresh

When the team turns on "Block materialization on failing checks", a materialized view's error-severity checks run on each refresh before it is published.
If one fails:

- The view's run shows an error that starts with `Not published:` (see `view-run-history`).
- The previous version of the view keeps serving queries.
- Downstream views in the same DAG are skipped for this run.
- The view's schedule is not paused.
  The next scheduled refresh runs the checks again.

Warn-severity checks never block a refresh.

### Step 5: Recover

Fix the cause, then prove it:

1. Fix the upstream data, or fix the assertion with `posthog:data-quality-check-update`.
   If the failure is real but must not block the refresh, change `severity` to `warn`.
2. For a blocked view, call `view-run` to materialize it again.
   Otherwise call `posthog:data-quality-check-run`.
3. Read `posthog:data-quality-check-results` again and confirm the newest run passed.

## Important notes

- Do not change a check's severity or assertion only to turn it green.
  Confirm with the user first.
- `errored` is never evidence of bad data, and `passed` on an empty table is not evidence of good data.
- A check reports against its subject, but a `custom_sql` query can read other tables.
  Read the query before you blame the subject.

## Related

- `authoring-data-quality-checks`: writing and choosing checks
- `auditing-warehouse-view-health`: finding failing materialized views
