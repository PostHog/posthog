# Evaluation backfills

A backfill runs an existing evaluation over a past time range.
The live scheduler grades units as they arrive, so a backfill covers traffic that arrived before the evaluation did, or before its conditions changed.
A unit is whatever the evaluation targets: a generation, a trace, or a session.

The Backfills tab and the five API endpoints are gated on the `llm-analytics-eval-backfills` feature flag, evaluated against the caller's organization and project.

## Reading the counters

| Counter            | Meaning                                                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `total_count`      | Units the estimate matched when the run was created. Excludes units that already held a result, unless `rerun_existing`. |
| `dispatched_count` | Units this run started an evaluation for.                                                                                |
| `skipped_count`    | Units the live path was already grading, so this run did not start a second one.                                         |
| `remaining_count`  | Units still holding no result when the run finished. Null means nothing counted them.                                    |

`dispatched_count + skipped_count` can end below `total_count`.
The estimate is a snapshot and the walk queries again as it goes, so an evaluation that runs live can grade a unit before the walk reaches it, and that unit stops being a candidate.

`remaining_count` is what says whether anything was left behind.
Zero means the window is covered, whoever graded it.
A higher number means units still owe a result, either held back by the settle horizon or left by a failed start.
It is counted when the run ends, so evaluations this run started may not have landed yet.

## An estimate of zero

An enabled evaluation covers its own traffic within minutes, so a range it has been running over holds nothing left to grade.
The estimate returns `total_units` and `already_evaluated_units` for that reason: zero with a large second number means covered, not empty.
Grading such a range again needs `rerun_existing`.

## Sampling

A condition set carries a rollout percentage, and the backfill reproduces the live scheduler's bucket rather than sampling independently.
The scheduler hashes the unit key with md5 and reads the first four bytes as a big-endian integer, modulo 10,000; `_rollout_bucket` in `evaluation_conditions.py` rebuilds that in SQL.
Any other hash would pick a disjoint share of the population, so a 20% backfill would grade units the live path never will.

## Not grading a unit twice

Without `rerun_existing`, a backfilled evaluation takes the same workflow id the live scheduler uses.
A unit the live path already started therefore collides and is counted as skipped.
This is the designed path, though Temporal records the refused start as a failure, which reads alarming in its UI.

With `rerun_existing`, the id carries the backfill id instead, which sidesteps that guard on purpose.

A completed run means every unit was dispatched, not that every verdict has arrived.

## Queries

`backfill_candidates.py` holds the query shapes, and the estimate and the walk share them, so the number a user approves matches what runs.

Units are discovered on `events` rather than on `ai_events`.
`events` is sorted by `(team_id, toDate(timestamp), event, ...)`, so a range of days prunes to nearly the rows asked for, while `ai_events` is sorted by `(team_id, trace_id, timestamp)`, where a range with no trace id prunes nothing.
A condition that filters on a heavy property such as `$ai_input` is the exception, because only `ai_events` carries those: a second query settles the matching units over the trace ids the first one found.

## Operating one

Structured logs from the activities carry a run:

- `llma.evaluation_backfill_page` per page, with the candidates returned and whether the walk is exhausted.
- `llma.evaluation_backfill_advance` per cursor move, with the dispatched and skipped deltas.
- `llma.evaluation_backfill_remainder` once, with the measured remainder.
- `llma.evaluation_backfill_child_start_failed` when a start raises anything other than already-started.

They sit on the activities rather than in workflow code, because activity logs reach the logs product and workflow-side logs do not.

Two bounds:
a window reaches back at most 30 days, which is also the `ai_events` retention, so the oldest slice of a long run can expire before the walk arrives;
and the window end is held back by the evaluation's settle horizon, so the most recent units are not candidates yet.
