# Cohort eviction sweeps: batching and deferred requests

The cohort stream processor evicts aged-out behavioral state on a timer.
This doc says how one eviction request turns into work on a partition worker, what a failure costs, and what the metrics mean.
It covers `rust/cohort-stream-processor/src/workers/sweep_path.rs` and the `EvictionQueue` it drives.

## The shape

Every behavioral state carries a deadline, and each partition worker keeps its live keys in one deadline-ordered `EvictionQueue`.
A timer routes a `Sweep` message with a cutoff (`now - safety_margin`) to every owned partition.

A `Sweep` message does not evict anything.
It records a request on the worker's `SweepSchedule`.
The worker's turn loop then runs the work in bounded pieces:

| Term    | What it is                                                           |
| ------- | -------------------------------------------------------------------- |
| Request | One `Sweep` message: a cutoff, recorded and coalesced                |
| Pass    | One request's candidates: at most 10,000 due keys, grouped by person |
| Batch   | One turn's work: whole person groups from one team, at most 256 keys |

A batch reads its keys, produces the membership changes, commits the state, and recomposes the affected cohorts.
Then the worker selects again.

## Why deferred

Behavioral deadlines cluster.
A team's daily buckets all expire at that team's local midnight, so a large team's whole wave comes due on one tick.
Running that wave inline held the partition for as long as it took and allocated every state value at once.

Batching splits the cost two ways.
Peak memory tracks one batch rather than one wave, and live traffic waits one batch rather than one wave.

## Scheduling

The worker's select is ordered.
Highest priority first:

1. A sweep batch, but only for the one turn a live batch just earned it.
2. A live batch.
3. A sweep batch, when the live lane is empty.
4. A seed run.
5. Taking a new quantum of seeds.

Rule 1 is the alternation: after a live batch runs, the next turn belongs to the sweep, so a lane that is never empty cannot hold a due wave indefinitely.
Rule 3 keeps a pass moving when nothing else wants the worker, without waiting for the next timer tick.
Both sit ahead of seeds, because seed work is admitted backlog and eviction is not.

The turn is claimed before the live batch runs, not after, so every exit path from a live batch still yields the next turn.
A partition that keeps failing to produce therefore cannot starve eviction.

At most one pass is in flight.
A request that arrives while a pass is draining lands in a single pending slot, keeping the greatest cutoff, and starts a new pass once the current one is exhausted.
A pass keeps its own cutoff for its whole life.

## Selection and claim

Selection and removal are two steps.

`due_keys(cutoff, limit)` reads the soonest due keys without removing any of them.
`take_due(key, cutoff)` removes one key only if its **current** deadline is still strictly before the cutoff, and hands back that deadline.

This keeps the queue authoritative for the whole life of a pass.
Between selection and claim, an event can reschedule a key later and a merge can cancel it.
Either way the claim refuses, the key stays queued on its live deadline, and the sweep counts it under `not_due`.
Nothing is copied out of the queue that would have to be reconciled with it later.

## Grouping

A pass groups its candidates by person, and a batch packs whole person groups from one team.

Whole groups, because Stage 2 composes a cohort from all of a person's leaves.
Splitting one person across two batches would compose them twice against two different halves of their eviction, and the intermediate result could be wrong.

One team, because the filter snapshot and the composition are per team.

A person with more leaves than the batch target starts a batch and runs alone.
The target bounds the ordinary batch; it is not a byte limit, because one behavioral value grows with the window length.
Read `sweep_read_chunk_bytes` before assuming otherwise.

The whole-person guarantee holds within a pass, not across passes.
The 10,000-key cap is applied to the flat, deadline-ordered candidate list before grouping, and one person's leaves carry different deadlines, so a person can straddle the cap and compose against half their eviction until the next pass picks up the rest.
That converges, and the unbatched loop this replaced behaved the same way.

## Ordering and failure boundaries

Within a batch:

1. Read the states and calculate the transitions.
2. Produce the single-leaf membership changes and await the acks.
3. Commit the behavioral state and the single-leaf registers.
4. Re-arm the queue deadlines the evictions imply.
5. Recompose Stage 2 for the affected leaves, then produce those changes and their cascades.

Steps 1 to 4 are at-least-once: a read, produce, or commit failure puts that batch's claimed keys back on the deadlines they were claimed at, and a later request retries them.
Batches that already settled stay settled; nothing rolls back and nothing is re-emitted.
A read failure abandons the batch before anything is applied, so there is no partial batch.

Step 5 keeps the existing at-most-once posture: `cf_stage2` is committed before its changes are published, so a failed publish is dropped and recovered on the person's next event.

One case does not return its keys: a batch whose team is absent from the catalog snapshot is discarded under `team_drift`, exactly as the unbatched path discarded it.
Those keys leave the queue and evict only on that person's next event.

Each batch takes a fresh output timestamp when it runs, not when its request arrived.
A batch that resumes after a live batch therefore stamps strictly newer than the change that live batch emitted, which is what a last-write-wins consumer needs.

A sweep can execute after later events in the same received live batch.
That is deliberate.
The request is deferred maintenance; ordinary message order is unchanged, and the claim revalidation plus the fresh timestamp are what make the deferral safe.

## Metrics

| Metric                                          | Reads as                                                                                                                              |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `sweep_batch_duration_seconds`                  | How long one batch held the worker. This is what live traffic waits behind                                                            |
| `sweep_cycle_duration_seconds{loop="eviction"}` | How long the **dispatch** took. It returns before any worker starts, so it is not a latency signal                                    |
| `sweep_batch_keys_claimed`                      | Keys one batch claimed. Bounded by the target, except for a person that runs alone, so the upper quantiles are the wide-person signal |
| `sweep_read_chunk_bytes`                        | Raw value bytes one read returned. The memory signal a key count cannot give                                                          |
| `sweep_queue_lag_seconds{partition}`            | How far the soonest queued deadline sits behind the newest cutoff. A level that grows across ticks means eviction is not keeping up   |
| `sweep_keys_evicted_total{variant}`             | Keys evicted                                                                                                                          |
| `sweep_keys_dropped_total{reason}`              | Keys selected but not evicted                                                                                                         |

Over a pass whose batches all settle, every selected key is counted once, under `sweep_keys_evicted_total` or `sweep_keys_dropped_total`.
A batch that fails its produce or commit is counted under neither until the request that retries it.

`not_due` is the one drop reason that is not a lost eviction.
It covers two causes: an event pushed the key's deadline past the cutoff, so it stays queued on the new deadline; or a merge cancelled it, so it is gone on purpose.
A steady `not_due` rate means passes are planning over keys that live traffic keeps saving, which is normal on an active partition.
Do not size an eviction backlog by summing `sweep_keys_dropped_total` across `reason` — read `sweep_queue_lag_seconds`.

## Worked example

A team with 1,000 people, one behavioral leaf each, all coming due at local midnight, on a partition whose live lane is busy.

- The timer routes one `Sweep` with cutoff `T`.
- The worker reaches that message inside its live batch and records the request there. Execution waits for the batch to finish its output and offset handling.
- Pass: 1,000 candidates, 1,000 person groups.
- Batch 1 claims 256 keys, reads them, produces up to 256 `Left` changes, commits, recomposes.
- The live lane takes the next turn.
- Batches 2 and 3 claim 256 each, batch 4 claims the last 232, each with a live batch between.
- The pass retires. No further work happens until the next tick.

Peak raw state held at any moment is one 256-key read, not 1,000.
Live latency added is one batch, four times, not one pass once.
