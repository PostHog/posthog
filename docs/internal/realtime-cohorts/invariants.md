# Invariants

This page collects the rules the realtime cohorts pipeline depends on.
Each one says what must hold, why, what keeps it true, and what breaks if it does not.
The linked pages explain the mechanisms in context.

When you change the pipeline, check your change against this list first.
Most of these are not enforced by a single test, and a violation usually shows up as silently wrong membership, not as an error.

## Definitions and the catalog

**1. A condition hash is a pure function of the compiled matcher, and every service treats it as the same 16 bytes.**

- Why: seed tiles, catalog entries and pinned backfill conditions find each other by this value.
- Kept by: Django hashes the bytecode serialized with sorted keys, and the Rust services never decode or recompute it.
- If broken: tiles miss their leaves, and a compiler change that alters the bytecode of an unchanged filter moves every affected hash.
- See [definitions and eligibility](definitions-and-eligibility.md#bytecode-and-the-condition-hash).

**2. The leaf state key derivation is frozen, and Django's behavioral shape hash moves whenever it would.**

- Why: behavioral state is keyed by it, and readiness is invalidated by the shape hash.
- Kept by: a golden vector test in Rust, and a Python shape hash over the same normalized fields.
- If broken: every stored row is orphaned at once, or an edit changes state without clearing readiness.

**3. The processor and the seeder interpret a definition with the same code.**

- Why: seeded state and live state must mean the same thing.
- Kept by: both link `cohort-core` for parsing, classification, state keys, windows, the HogVM configuration and day math.
  The seeder never enables cascades, so cohorts with references are the one place their verdicts differ.
- If broken: backfills write state the live path reads differently.

**4. A cohort with any leaf the pipeline cannot represent emits nothing.**

- Why: evaluating a cohort without one of its leaves gives wrong members, and no answer is safer than a wrong one.
- Kept by: a dropped leaf excludes its cohort first in the eligibility order.
- If broken: flags and workflows act on memberships computed from part of a definition.

**5. Static analysis of conditions fails wide.**

- Why: a read set that is too small silently changes answers, while one that is too wide only costs time.
- Kept by: every construct the analysis does not model, and any analysis over budget, falls back to "reads everything".
  Property-based tests compare evaluation on pruned and full inputs.

## Routing and the runtime

**6. Every message that can change a person's state reaches the worker that owns that person.**

- Why: workers keep state without locks, and a merge computes where the survivor lives.
- Kept by: the key `"{team_id}:{person_id}"`, Kafka's `murmur2` partitioner set explicitly on every Rust producer and computed by hand in Node, the partition count shared by configuration, and startup checks on the processor and the seeder.
  Node's merge producer computes its partition from its own setting, which nothing checks.
- If broken: state for one person splits across workers with no error.
- See [event routing](event-routing.md#partition-affinity).

**7. While a worker runs, it is the only writer of its partition's state.**

- Why: reads must see the worker's own previous writes, with no locks or snapshots.
- Kept by: every event, merge, cascade, sweep, backfill and reconcile step for the partition runs on its worker.
  A revoke wipes a slice after its worker exits, and a partition that moves in after boot is wiped just before its worker spawns.
- Limit: with durable restore on, nothing makes boot recovery finish before workers start.
  The events consumer dispatches polls that arrive before its assignment settles, and the followers start once the catalog loads, so a worker can run while the boot redrive clears outbox rows.
  This is a gap in the ordering, not a reproduced failure.
  See [processor runtime](processor-runtime.md#startup).

**8. A committed offset never runs ahead of state on disk.**

- Why: writes do not wait for the disk, so a crash can lose recent writes, and Kafka must still redeliver them.
- Kept by: every consumer forces the write-ahead log to disk before each commit, and skips the commit if that fails.
- If broken: a crash loses writes whose inputs are never redelivered.
- Limit: it covers writes that succeeded.
  A live event skipped on a store error, a wiped slice, and a follower rewind that failed after a checkpoint restore are outside it.
- See [state store and durability](state-store-and-durability.md#the-durability-invariant).

**9. A later success never commits past an earlier failure that set a floor.**

- Why: merges, cascades, seeds and reconcile requests must be retried, not skipped.
- Kept by: held and deferred floors in each offset tracker, and holdovers that retry older messages before newer ones.
- Note: the live event path sets no floor, which is why live output is at most once.

**10. Live work comes first.**

- Why: backfill must not make membership stale.
- Kept by: each worker checks its live lane before its seed lane, seed runs are sized by a row budget, and seeds pause when the live watermark lags.
  The sweep alternates with live batches so neither starves the other.
- Limit: a seed heavier than the whole row budget still applies in a run of its own, so the budget does not cap how long live work waits behind that one run.

## Live evaluation

**11. Each event's Stage 1 changes commit as one atomic batch before the next event reads.**

- Why: counters, stamps and replay marks are read, modified and written.
- Kept by: one staged write batch per event, awaited before the next event.

**12. A redelivered event changes nothing.**

- Why: input is at least once.
- Kept by: per-row replay marks, the highest firehose offset applied from each firehose partition.
- Assumes: one person's events from one firehose partition arrive in offset order.
  An event overtaken by a later one from the same firehose partition is skipped as a replay.
- Limit: the marks live inside their row.
  Once the sweep deletes a row, or the person record time-to-live expires a record, a redelivered old event is folded again.

**13. Stage 1 never reads the wall clock.**

- Why: replaying the same events must give the same state.
- Kept by: windows advance with event time on the live path, and only the sweep moves them with time.
- Consequence: a leaf's answer "as of now" is right only after the sweep has run.

**14. Stage 2 recomputes the whole cohort from stored state and compares it with the stored bit.**

- Why: composition must be idempotent and self-correcting.
- Kept by: one recompute-and-diff routine shared by the live, sweep, merge, cascade, seed and reconcile paths.
  A `left` writes an explicit `false` so reconcile can find the person later.
- Each path decides what to emit from the diff.
  Every path except reconcile emits only when the stored bit changes, and reconcile emits every row it walks.

**15. Every time-bounded row sits in the eviction queue at its current deadline.**

- Why: a person who sends no events leaves only through the sweep.
- Kept by: every fold reschedules its row, the sweep re-arms rows it keeps, and a worker rebuilds its queue at spawn when durable restore is on.
- If broken: dormant members never leave.
- Limit: a sweep drops a key without rescheduling it when its team is missing from the catalog, or its leaf, row or encoding is gone or bad.
  That row waits for the person's next matching event, or for a durable-restore rebuild when a worker spawns.

**16. A merge is applied once, and its state survives until it is applied.**

- Why: merge messages and transfers are redelivered, redriven and retried.
- Kept by: drain and apply markers keyed by the original merge message, and an outbox row that is cleared only after the transfer is acknowledged.
- Limit: markers are local to a partition and expire after their retention, and a revoke or a wipe deletes the outbox with the rest of the slice.
- See [merges and cascades](merges-and-cascades.md).

**17. Cascades are bounded.**

- Why: cohorts can reference each other in chains and cycles.
- Kept by: cohorts in a reference cycle are excluded at catalog build, and each cascade message carries a depth and a chain checked on every hop, plus a fan-out cap.

## Backfill

**18. A run never seeds its boundary day or any later day.**

- Why: on the boundary day, the live count and a seed would be two partial counts of one day, which neither `max` nor `+` can merge correctly.
- Kept by: a run seeds only whole team-timezone days before the day of its boundary.
- Note: earlier days can hold live counts as well, from events live folded after loading the leaf and from late events.
  That overlap is expected, and invariants 19 and 20 make it safe.
- See [backfill overview](backfill-overview.md#rule-1-split-days-at-a-boundary).

**19. Seeds carry absolute values and merge idempotently.**

- Why: seeds are produced at least once and applied again after failures.
- Kept by: day tiles carry absolute counts merged with `max`, and a person seed applies only when its scan is fresher than the record's stamp.
- Limit: a person seed that changes nothing leaves no stamp, so person seeds from different runs are not ordered by scan time.

**20. A day tile applies only after the live path should have folded every event the tile counted.**

- Why: otherwise live adds a count on top of a tile that already has it.
- Kept by: the scan counts only events that reached ClickHouse before the chunk's claim instant, and the processor holds each tile until the partition's live watermark passes that instant plus a margin.
- Limit: it holds only while the live topic trails ClickHouse by less than the margin.
  An event the shuffler abandoned never reaches the live path, so only the tile counts it, which `max` handles correctly.

**21. Seeds never touch replay marks.**

- Why: replay marks track live topic offsets, and seed offsets would collide with them.
- Kept by: every seed merge copies the marks through unchanged.

**22. A seed slides a window before it counts into it.**

- Why: applying an expired day would resurrect a row and cause an `entered` then `left` flap.

**23. A reconcile request runs on each partition only after that partition applied the run's earlier seeds.**

- Why: a marker must certify the run's seeds on that partition.
- Kept by: per-partition order on the seed topic, and admission that never lets a later message overtake a held one.
- Limit: a seed run that fails before its Stage 1 commit does not stop a later reconcile in the same tenure.
  A seed re-keyed to a merge survivor on another partition joins the back of that partition, so that partition's marker does not cover it.

**24. Reconcile emits every Stage 2 row, and a request whose kind hash no longer matches emits nothing.**

- Why: live output is at most once, so only a full re-telling repairs downstream, and a stale definition must never be certified.
- Kept by: the walk emits members and explicit non-members alike, and each request carries the pinned shape hash of its kind, checked on every drain.
- Limit: the walk composes the processor's current tree, and the guard ignores the composition and the other kind's hash.
  Django's finalizer checks those before it stamps.
- Limit: the walk covers only rows the store holds.
  It cannot restore a skipped event or find a person whose first Stage 2 row was never written.

**25. A run completes only with proof.**

- Why: readiness must not be certified over unplanned days, unproduced seeds or missing markers.
- Kept by: the move to `reconciling` requires the planning proof and every chunk confirmed.
  A short cohort is settled only after the processor has committed past every reconcile request and the marker topic has been read to its end.
  Every outcome write is fenced by the dispatch epoch, and `reconcile_observed_at` is written last.
- Limit: the proof covers planned days, not persons.
  Raising the seeder's band count while a run is seeding leaves persons unscanned, and every chunk still confirms.
- See [completion and readiness](completion-and-readiness.md).

**26. A readiness stamp vouches only for the definition its run replayed.**

- Why: flags read the membership table on the strength of the stamp.
- Kept by: an edit clears the stamp in the same write that stores the new definition, while the cohort stays realtime on an allowlisted team and the hash maintenance succeeds.
  The finalizer stamps with a compare-and-set on the pinned shape hash, refuses a run that predates a composition repair, and never stamps from a superseded participation.
- Limit: the maintenance is best effort.
  If hashing fails, the save still stores the new definition, and the old stamp stays.

**27. At most one open participation in an active run exists per cohort and kind.**

- Why: a stamp must come from exactly one backfill of the current definition.
- Kept by: partial unique indexes on active runs, and the creators' check of open participations under a lock on the cohort row.

## Membership output

**28. The newest change for a cohort and person wins.**

- Why: changes arrive late, twice, and out of order.
- Kept by: the consumer applies a change only if its version is at least the stored one, and versions increase strictly within one worker's tenure on a processor partition.
- Limit: across a restart or a partition move, version order follows the wall clock.
  A change with no usable version bypasses the ordering.
- See [membership output and readers](membership-output-and-readers.md).

**29. Membership rows, snapshot bookkeeping and consumer progress commit together.**

- Why: the sweep trusts progress to mean the rows are there.
- Kept by: one transaction per batch, when `COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED` is on.
  With it off, the consumer does a plain upsert and records no progress, and the sweep cannot run.

**30. The sweep deletes only rows the latest reconcile did not re-assert, and only after they could have arrived.**

- Why: a premature sweep deletes members whose re-assertion is still queued.
- Kept by: the threshold is the lower of the snapshot's and the markers' lowest versions, and the sweep waits until the consumer has applied the membership topic up to the ends captured after all markers arrived.

**31. Readers trust only `in_cohort = true`, and flags read the table only with positive proof of readiness.**

- Why: the table holds non-members too, and an unready cohort's table is incomplete.
- Kept by: both readers filter on `in_cohort`, and the flags service routes a cohort to the table only for enabled teams, realtime cohorts with a behavioral condition, and stamps its policy accepts.

## Delivery, in one table

| Path                                                                                                    | Guarantee                            | What repairs a loss                 |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------ | ----------------------------------- |
| Firehose to stream topic                                                                                | At least once, with counted abandons | Backfill                            |
| Node to person merge events                                                                             | At most once, uncounted              | Backfill, for the survivor's counts |
| Live event to membership change                                                                         | At most once                         | Reconcile                           |
| Merge membership output, composed sweep output, first-hop cascades from the live, merge and sweep paths | At most once                         | Reconcile                           |
| Single-leaf sweep output, cascade handling, merge state                                                 | At least once                        | Retries within the path             |
| Seeds and reconcile, including their first-hop cascades                                                 | At least once                        | Replays after holds                 |
| Membership consumer                                                                                     | At least once, applied idempotently  | The version guard                   |

"At most once" means the path never retries a failed produce.
It does not rule out duplicates: a store that loses unflushed writes, or is wiped, replays its inputs against older state and can emit a change a second time.

Reconcile repairs lost output, not lost state.
It re-tells the rows the store holds.
An event that Stage 1 skipped needs a later seed that covers it, and a person whose first Stage 2 row was never written needs a seed or a leaf flip that touches them.

The system is built on one bargain: live paths favor speed and may lose a change, and every backfill ends with a reconcile that re-tells everything the store holds.
Anything that stops reconcile from running, or from covering a cohort, leaves downstream wrong with no signal.
