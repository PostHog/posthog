# Evaluation backfills

A backfill runs an existing evaluation over a past time range.
The live scheduler grades units as they arrive, so a backfill exists for the traffic that arrived before the evaluation did, or before its conditions changed.

The surface is the Backfills tab on an evaluation.
Both the tab and the five API endpoints are gated on the `llm-analytics-eval-backfills` feature flag, evaluated against the caller's organization and project.

## What a unit is

A unit is one generation, one trace, or one session, decided by the evaluation's target.
The backfill freezes the target on the row at creation, so editing the evaluation mid-run does not change what the walk dispatches against.

## Reading the counters

A row carries four numbers, and they mean different things.
Confusing them is the most common way to misread a finished run.

| Counter            | Meaning                                                                                                                 |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `total_count`      | Units the estimate found **without a result**, measured when the run was created. Not the number of units in the range. |
| `dispatched_count` | Units this run started a child workflow for.                                                                            |
| `skipped_count`    | Units whose child workflow already existed, so the live path was already grading them.                                  |
| `remaining_count`  | Units in the window still holding no result when the run finished, counted at that moment.                              |

`dispatched_count + skipped_count` can end below `total_count`, and that is normal.
The estimate is a snapshot, while the walk queries again on every tick.
An evaluation that runs live keeps grading its own traffic, so units counted as owing a result at creation can hold one by the time the walk reaches them.
Those units simply stop being candidates.

`remaining_count` is what says whether anything was left behind.
Zero means the window came out covered, whoever graded it.
A non-zero value means units still owe a result: they were held back by the settle horizon, or their child start failed.
Children this run started may not have landed when the count runs, so a busy run can report a remainder that later clears.

## Why an estimate of zero is normal

An enabled evaluation covers its own traffic within minutes.
Ask for a range it has been running over and the answer is zero, because the dedupe excludes everything that already holds a result.

The estimate reports both halves for that reason: `total_units` is what would be graded, and `already_evaluated_units` is what already holds a result.
A zero with a large `already_evaluated_units` means the range is covered, not that the range is empty.
Grading it again needs `rerun_existing`.

## Sampling

A condition set carries a rollout percentage, and the backfill reproduces the live scheduler's bucket rather than sampling independently.
The scheduler hashes the unit key with md5 and reads the first four bytes as a big-endian integer, modulo 10,000.
`_rollout_bucket` in `evaluation_conditions.py` rebuilds that in SQL.
Any other hash would select a disjoint share of the population, and a 20% backfill would grade units the live path never will.

## Not grading a unit twice

Without `rerun_existing`, a child workflow takes the same id the live scheduler uses, including its `-ingestion` suffix.
A unit the live path already started therefore collides, and Temporal refuses the start with `WORKFLOW_ALREADY_EXISTS`.
The walk counts that as skipped.
This is the designed path, not a failure, although the Temporal UI paints the event red.

With `rerun_existing`, the child id carries the backfill id instead, which sidesteps the at-most-once guard on purpose.

## Where the work happens

`EvaluationBackfillWorkflow` owns one row and walks it newest first.
Each tick prepares, fetches a page of candidates, starts a child per candidate, then advances the cursor.
The walk continues as new every tick, so history stays bounded.

Children start with `ParentClosePolicy.ABANDON`, so the row reaching `completed` means every unit was dispatched, not that every verdict has arrived.

## Queries

`backfill_candidates.py` holds the query shapes, and the estimate and the walk share them so the number a user approves matches what the workflow grades.

Units are discovered on `events` rather than on `ai_events`.
`events` is sorted by `(team_id, toDate(timestamp), event, ...)`, so a range of days prunes to nearly the rows asked for.
`ai_events` is sorted by `(team_id, trace_id, timestamp)`, where a range with no trace id prunes nothing.
A condition that filters on a heavy property, such as `$ai_input`, is the exception: only `ai_events` carries those, so a second query settles the matching units over the trace ids the first one found.

## Operating one

Structured logs from the activities carry the run:

- `llma.evaluation_backfill_page` on each page, with how many candidates it returned and whether the walk is exhausted.
- `llma.evaluation_backfill_advance` on each cursor move, with the dispatched and skipped deltas.
- `llma.evaluation_backfill_remainder` once at the end, with the measured remainder.
- `llma.evaluation_backfill_child_start_failed` when a start raises anything other than already-started.

Those come from activities rather than from workflow code, because activity logs reach the logs product and workflow-side logs do not.

Two bounds worth knowing.
A window can reach back 30 days, which is also the `ai_events` retention, so the oldest slice of a long run can expire before the walk arrives.
The window end is held back by the evaluation's settle horizon, so the most recent units are not candidates yet.
