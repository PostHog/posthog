# Time, windows and eviction

A behavioral leaf such as "viewed pricing in the last 7 days" can become false without any event.
The person simply stops doing the thing, and time passes.
This page explains how the processor models time and how the eviction sweep produces "left because time passed".

It assumes the vocabulary of [live evaluation](live-evaluation.md): leaves, their state variants, Stage 1, which keeps each leaf's state, and Stage 2, which recomposes cohorts when a leaf flips.

## Days belong to the team's timezone

Behavioral windows counted in days use calendar days in the team's timezone.
An event at 02:30 UTC on 2026-09-18 belongs to 2026-09-17 for a team in `America/New_York`.

The processor turns a timestamp into a **day index**, the number of days since 1970-01-01 in the team's timezone.
That direction is never ambiguous.
The reverse, the instant a given day starts, needs two rules around daylight saving changes, and every daily deadline uses it:

- when local midnight happens twice, the day starts at the earlier instant,
- when local midnight falls inside a skipped hour, the day starts at the first valid instant after the gap.

The timezone comes from the team row when the catalog is built.
An unknown timezone falls back to UTC and is counted.

## What "the last N days" means

A window of N days covers today plus the N days before it, so N + 1 calendar days.
"The last 7 days" on 2026-09-24 covers 2026-09-17 through 2026-09-24.

For `performed_event` this matches the batch cohort query, which also starts the window at local midnight N days ago.
For `performed_event_multiple`, the batch query uses a rolling `now - N days` instead, so the realtime window can hold up to one extra partial day.

Months count as 30 days and years as 365 days.
The batch query uses calendar months and years, so month and year windows differ from it at the edges.
The gap grows with the window: one month can be a day or two off, and 12 months are 360 days here against 365 or 366 in the batch query.

Hour and minute windows are durations, not calendar days.
Only `performed_event` supports them.
A count leaf with an hour or minute window is not supported and has no state.

A `performed_event` window written with absolute dates, using `explicit_datetime` and `explicit_datetime_to`, is a fixed calendar range, so a match inside it never expires.
`performed_event_multiple` does not support absolute dates.
A relative `explicit_datetime` such as `-30d` with no upper bound slides like `time_value`.

## Every row carries its own deadline

Stage 1 never reads the wall clock.
Instead, every time it folds an event into a behavioral row, it computes the row's **eviction deadline**: the earliest instant at which the leaf's answer could change without another event.

| Variant                                             | Deadline                                                                                                             |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `performed_event` with a window in days             | Local midnight at the start of day `newest match + N + 1`                                                            |
| `performed_event` with a window in hours or minutes | `newest match + window`                                                                                              |
| `performed_event` with absolute dates               | None                                                                                                                 |
| Daily buckets or compressed history                 | Local midnight at the start of day `oldest counted day + N + 1`, the moment the oldest counted day leaves the window |
| Person-property leaves                              | None. The sweep never touches them                                                                                   |

A `performed_event` leaf with a 7-day window, matched at 11:00 on day D, stays true through the end of day D + 7 and expires at midnight starting day D + 8.
It does not expire at "match time + 7 × 24 hours".

A daily-buckets leaf's deadline is only the next moment its total can drop.
When the oldest day slides out, the total may still satisfy the operator, and the row simply gets a later deadline.

## The eviction queue

Each worker keeps an in-memory **eviction queue** of its partition's behavioral rows, ordered by deadline.
Every fold reschedules its row at the new deadline, earlier or later, replacing the old entry exactly.
Rows with no deadline are never queued.

The queue lives only in memory.
With durable restore enabled, a worker rebuilds it from its slice of behavioral state when it spawns, before it handles its first message.
A worker spawns only when its partition's first message arrives, so after a restart that partition's overdue evictions wait for that message.
[Processor runtime](processor-runtime.md) explains worker lifecycle and durable restore.

## The sweep

A timer fires every 30 seconds, after an initial delay at boot.
Each tick sends a sweep request to every running worker with a **cutoff** of `now - safety margin`.
The margin, 5 minutes by default, absorbs up to that much consumer lag.
A person whose events are still sitting in the input topic should not be evicted just because the processor is behind.
With more lag than the margin, a person can leave and then re-enter when the delayed event arrives.

The worker does not sweep on receipt.
It records the request, keeping only the latest cutoff, and works through it on later turns.

1. **Select.**
   Up to 10,000 due keys are selected from the queue in deadline order, then grouped by person.
   Due keys beyond that wait for the next tick.
2. **Batch.**
   Whole persons from one team, as far as this pass selected them, are packed into a batch of about 256 keys.
   Each key is claimed only if its deadline is still due, so a key that an event rescheduled since selection is skipped.
3. **Read.**
   The batch's rows are read with one batched read that uses the maintenance I/O permits, the pool reserved for background work.
4. **Evict.**
   - A `performed_event` row past its deadline is deleted.
     If it matched, the leaf flips to false.
   - A daily or compressed row slides its window to the cutoff's day and recomputes its total.
     The leaf can flip either way.
     With `lte 2`, `lt 3` or `eq 2`, a total falling from 3 to 2 makes the leaf true again.
     A total that falls to zero is never a member.
     The row is rewritten and rescheduled at its next deadline, or deleted when it has no counts left.
5. **Emit.**
   Flips go through the same leaf-to-cohort lookup as live events.
   A flip of a single-leaf cohort becomes a change directly.
   A flip of a leaf in a composed cohort triggers Stage 2 for that person and cohort.

Sweep batches alternate with live batches on the worker.
Neither can starve the other, and a sweep never holds the whole partition while a large wave of deadlines expires.

The 10,000-key cut comes before the grouping, so it can split one person's due leaves across two passes, about one tick apart.
Keys that share a deadline sit in the order they were scheduled, so in a midnight wave the cut can split many persons, not only the last one.
Between the two passes, Stage 2 composes against half of the person's evictions.
Take `AND[A, NOT B]` with A and B due at the same midnight: if the first pass evicts only B, the cohort emits `entered`, and the second pass then emits `left`.

A batch drops its keys without rescheduling them when their team is missing from the catalog, including before the first catalog load, and when a key's leaf, row or encoding is gone or bad.
Those rows are not scheduled again until the person's next matching event, or a durable-restore rebuild.

### Delivery on the sweep

The two kinds of sweep output make different promises.

- **Single-leaf cohorts** are produced first and committed after the acknowledgment.
  If the produce or the commit fails, the keys go back on their deadlines and the next pass retries them.
  This is at least once while the worker runs.
  The retry lives in the in-memory queue.
  After a restart it survives only with durable restore on, where the row is still on disk and the rebuild at spawn queues it again.
  With durable restore off, the restart wipes the store, and the missed `left` is lost with the rest of the state.
- **Composed cohorts** are committed by Stage 2 first and produced after.
  A failed Stage 2 read, commit or produce is dropped.
  This is at most once.
  Downstream stays wrong until the cohort flips again for that person, or until a backfill run's reconcile re-emits the cohort.

## Why deadlines cluster at midnight

Daily windows expire at local midnight, so a team's rows reach their deadlines together, just after midnight in that team's timezone, plus the safety margin.
For a large team that is a wave of evictions at once.
The sweep is bounded for this reason.
It reads and writes a small batch at a time, interleaved with live traffic, so the wave costs a steady trickle of work instead of a memory spike and a stall of the live path.

## Worked example

This continues from "The third pageview" in [live evaluation](live-evaluation.md#worked-example), and assumes p-1 keeps their email.
Team 7 uses UTC, and cohort 42 is `AND[A, B]`, with A = "3 or more `/pricing` pageviews in the last 7 days" and B = "email is set".

p-1 made 3 matching pageviews on 2026-09-14 and entered cohort 42.
A's row has all 3 counts on day 2026-09-14.
Its deadline is midnight starting 2026-09-14 + 7 + 1 = 2026-09-22.

p-1 sends nothing more.

1. At 2026-09-22 00:05:15 UTC a tick fires with cutoff 00:00:15, the first cutoff past A's deadline.
2. On its next sweep turn, the worker for partition 26 selects A's row for p-1 and claims it.
3. The window slides to the cutoff's day, 2026-09-22.
   The window now starts on 2026-09-15, so the three counts from 2026-09-14 fall out.
   The total drops to 0, and A flips to false.
   The row has no counts left, so it is deleted.
4. No single-leaf cohort uses A.
5. Stage 2 recomposes cohort 42 for p-1: A is false, B is true, so `AND` is false.
   The stored bit is true, so this is a flip.
   Stage 2 writes `false` and the worker produces `left`.

p-1 was a member from 2026-09-14 14:00 until about 00:05 on 2026-09-22.
"The last 7 days" covered 8 calendar days, and the safety margin plus the tick interval added a few minutes on top.

**Variant.**
Suppose p-1 had made one more matching pageview on 2026-09-20.
That event slides the window to end on 2026-09-20, which drops nothing because 2026-09-14 is still inside, and adds a count on 2026-09-20.
The oldest counted day is still 2026-09-14, so the deadline stays 2026-09-22.
At the sweep on 2026-09-22 the total drops from 4 to 1, A still flips to false, and the row is rewritten with a new deadline of midnight starting 2026-09-28 instead of being deleted.

## Things that surprise people

- Every `left` produced by time carries the safety margin as extra latency.
  A leaf with a one-hour window leaves more than 5 minutes after the hour ends.
- Windows advance with event time on the live path.
  For a person with no state for a leaf, a late event older than the window creates state anchored at its own old day, emits `entered`, and is swept out on the next tick.
- The sweep can emit `entered`, for operators like `lte`, `lt` or `eq`.
- With cascades on, a sweep expiry of a single-leaf cohort sends no cascade message.
  A cohort that only references it keeps the person and never emits the missed `left`.
  Its answer is right again only if the person re-enters, or after a reconcile.
- Person-property leaves have no window, so the sweep never expires them.
  With the default settings, "email is set" stays true until an event carries properties without an email.
  The exception is the optional person record time-to-live, off by default, which deletes a dormant person's whole record.
  After that, a recomposition or a reconcile reads the person's conditions as not matching, with no `left` emitted at the moment of deletion.
  [State store and durability](state-store-and-durability.md#keeping-the-store-bounded) describes it.
